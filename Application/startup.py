import boto3
import os
import time

AWS_REGION = "us-east-1"

# ECS Details
ec2_client = boto3.client('ec2', region_name=AWS_REGION)
ec2_resource = boto3.resource('ec2', region_name=AWS_REGION)
ecs_client = boto3.client("ecs", endpoint_url="https://ecs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
s3_client = boto3.client('s3',region_name=AWS_REGION)
s3_resource = boto3.resource('s3',region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
iam_client = boto3.client('iam')
autoscale_client = boto3.client("autoscaling")
app_autoscale_client = boto3.client('application-autoscaling')
load_balance_client = boto3.client('elbv2')
sqs_client = boto3.client('sqs',endpoint_url="https://sqs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
sqs_resource = boto3.resource('sqs',endpoint_url="https://sqs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
cloud_client = boto3.client('cloudwatch', region_name=AWS_REGION)
event_client = boto3.client('events', region_name=AWS_REGION)
ssm_client = boto3.client('ssm')

cluster_name = "BotoCluster"
account_number = boto3.client('sts').get_caller_identity().get('Account')

# get vpc id ---------------------------------------------------------------------------
vpc_id = ec2_client.describe_vpcs().get('Vpcs', [{}])[0].get('VpcId', '')

# get security groups ---------------------------------------------------------------
default_sg = ec2_client.describe_security_groups(GroupNames=['default'])['SecurityGroups'][0]['GroupId']

# find subnet id -----------------------------------------------------------------------------------
def ec2_get_subnet_list():
    response = ec2_client.describe_subnets()
    return response['Subnets']

subnet1 = ec2_get_subnet_list()[0]['SubnetId']
subnet2 = ec2_get_subnet_list()[1]['SubnetId']

# create queues --------------------------------------------------------------------
clientResultQueue = sqs_resource.create_queue(QueueName='clientResultQueue', Attributes={'DelaySeconds': '2'})
workQueue = sqs_resource.create_queue(QueueName='workQueue', Attributes={'DelaySeconds': '2'})
splitResultQueue = sqs_resource.create_queue(QueueName='splitResultQueue', Attributes={'DelaySeconds': '2'})
scaleUpLambdaQueue = sqs_resource.create_queue(QueueName='scaleUpLambdaQueue', Attributes={'DelaySeconds': '2'})

# Create buckets -----------------------------------------------------------------
s3_resource.create_bucket(Bucket='client-upload-work-bucket')
split_work_bucket = s3_resource.create_bucket(Bucket='split-work-bucket')
s3_resource.create_bucket(Bucket='split-results-bucket')
s3_resource.create_bucket(Bucket='stitch-count-lambda-bucket')
s3_resource.create_bucket(Bucket='client-results-bucket')
s3_resource.create_bucket(Bucket='stitch-python-bucket')

def launch_stitch_instance():
    s3_resource.Bucket('stitch-python-bucket').upload_file('stitch_image.py', 'stitch_image.py')
    user_data = '''#!/bin/bash
    aws s3 cp s3://stitch-python-bucket/stitch_image.py home/ec2-user/stitch_image.py
    sudo pip install numpy ; pip install matplotlib ; pip install boto3
    sudo python3 /home/ec2-user/stitch_image.py'''

    instances = ec2_resource.create_instances(
        ImageId='ami-07f0e3bc668c5a72c', 
        MinCount=1, 
        MaxCount=1,
        InstanceType='t2.micro',
        KeyName='lab-key',
        IamInstanceProfile={
                'Name': 'LabInstanceProfile'
        },
        TagSpecifications=[
                {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': 'Stitch-instance'
                    }
                ]}
            ],
        UserData=user_data
        )

# Launch an ecs cluster -----------------------------------------------------------------------
def launch_ecs_example():
    ecs_client.create_cluster(
        clusterName=cluster_name,
        configuration = {
            'executeCommandConfiguration': {
                'kmsKeyId': 'lab-key',
                'logging': 'DEFAULT'
            }
        },
    )

    instances = ec2_resource.create_instances(
        ImageId='ami-0fe5f366c083f59ca', 
        MinCount=1, 
        MaxCount=1,
        InstanceType='m5.large',
        KeyName='lab-key',
        IamInstanceProfile={
                'Name': 'LabInstanceProfile'
        },
        UserData="#!/bin/bash \n echo ECS_CLUSTER=" + cluster_name + " >> /etc/ecs/ecs.config",
        NetworkInterfaces=[{
        'SubnetId': subnet1,
        'DeviceIndex': 0,
        'AssociatePublicIpAddress': True,
        'Groups': [default_sg]
            }],
        TagSpecifications=[
                {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': 'First-instance'
                    },]
            }   ,
            ]
        )

    # Wait for the instance to enter the running state
    instances[0].wait_until_running()

    response = event_client.put_rule(
        Name='EC2HealthChange',
        EventBusName='default',
        EventPattern='{"source": ["aws.ec2"], "detail-type": ["EC2 Instance State-change Notification"], "detail": {"state": ["stopped", "shutting-down"]} }',
        State='ENABLED',
        RoleArn='arn:aws:iam::'+account_number+':role/LabRole',

    )

    response = event_client.put_targets(
        Rule='EC2HealthChange',
        Targets=[
            {
                'Arn': 'arn:aws:lambda:us-east-1:'+account_number+':function:scale_up_lambda',
                'Id': 'Id91e55426-5439-4ecf-a10e-4f751abc44aa',
            }
        ]
    )

    # print(response)

    ecs_client.register_task_definition(
        family = "CCBDTaskv22",
        taskRoleArn= "arn:aws:iam::"+account_number+":role/LabRole",
        executionRoleArn= "arn:aws:iam::"+account_number+":role/LabRole",
        networkMode = "awsvpc",
        containerDefinitions = [
            {
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                "awslogs-group": "/ecs/ContainerLogGroup",
                "awslogs-region": "us-east-1",
                "awslogs-stream-prefix": "ecs"
                }
            },
            "entryPoint": [],
            "command": [],
            "cpu": 128,
            "environment": [],
            "mountPoints": [],
            "memoryReservation": 128,
            "volumesFrom": [],
            "image": "pragyagg/workerfile-ccbd:v22",
            "essential": True,
            "name": "worker_task"
            }
        ],
        placementConstraints= [],
        memory = "512",
        requiresCompatibilities = [
            "EC2"
        ],
        cpu = "256",
        volumes= []
        )

    
    
    ecs_client.create_service(
        cluster=cluster_name, 
        serviceName="Service_1",
        taskDefinition='CCBDTaskv22',
        desiredCount=2,
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': [subnet1],
                'securityGroups': [default_sg],
            }
        },
        launchType='EC2',
    )

# AUTOSCALE and Policy -------------------------------------------------------------------------------

# Create alarm
cloud_client.put_metric_alarm(
    AlarmName='NumberOfMessagesOnWorkerQueue',
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='NumberOfMessagesReceived',
    Namespace='AWS/SQS',
    Period=120,
    Statistic='SampleCount',
    Threshold=3,
    ActionsEnabled=True,
    AlarmActions=[
        'arn:aws:cloudwatch:us-east-1:'+account_number+':alarm:TargetTracking-service/BotoCluster/Service_1-AlarmLow-5938aff9-63b9-49b0-8022-8ea035819ecb',
        'arn:aws:cloudwatch:us-east-1:'+account_number+':alarm:TargetTracking-service/BotoCluster/Service_1-AlarmHigh-189d8694-ee75-4cae-af94-148e8a4cc251',
    ],
    AlarmDescription='ApproximateNumberOfMessagesVisible >= 4 for 1 datapoints within 5 minutesApproximateNumberOfMessagesVisible >= 4 for 1 datapoints within 5 minutes',
    Dimensions=[
            {
            'Name': 'QueueName',
            'Value': 'workQueue'
            }
    ]
)

def add_autoscale():
    app_autoscale_client.register_scalable_target(
        ServiceNamespace='ecs',
        ResourceId='service/BotoCluster/Service_1',
        ScalableDimension="ecs:service:DesiredCount",
        RoleARN='arn:aws:iam::'+str(account_number)+':role/aws-service-role/ecs.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_ECSService',
        MinCapacity=1,
        MaxCapacity=8
    )

    app_autoscale_client.put_scaling_policy(
        PolicyName='ECS-CPU-policy',
        PolicyType='TargetTrackingScaling',
        ResourceId='service/BotoCluster/Service_1',
        ScalableDimension='ecs:service:DesiredCount',
        ServiceNamespace='ecs',
        TargetTrackingScalingPolicyConfiguration={
            'TargetValue': 60,
            'PredefinedMetricSpecification': {
                'PredefinedMetricType': 'ECSServiceAverageCPUUtilization'
            },
            'ScaleOutCooldown': 60,
            'ScaleInCooldown': 60,
        }   
    )

    app_autoscale_client.put_scaling_policy(
        PolicyName='ECS-SQS-policy',
        PolicyType='TargetTrackingScaling',
        ResourceId='service/BotoCluster/Service_1',
        ScalableDimension='ecs:service:DesiredCount',
        ServiceNamespace='ecs',
        TargetTrackingScalingPolicyConfiguration={
            'CustomizedMetricSpecification': {
                'MetricName': 'NumberOfMessagesReceived',
                'Namespace': 'AWS/SQS',
                'Dimensions': [
                    {
                    'Name': 'QueueName',
                    'Value': 'workQueue'
                    },
                ],
                'Statistic': 'SampleCount',
            },
            'TargetValue': 3,
            'ScaleOutCooldown': 60,
            'ScaleInCooldown': 60,
        }   
    )

# Create Lamda function ----------------------------------------------------------
def create_scale_up_lambda():
    with open('scale_up_lambda.zip', 'rb') as f:
        zipped_code = f.read()

    labrole = iam_client.get_role(RoleName='LabRole')

    lambda_response = lambda_client.create_function(
        FunctionName='scale_up_lambda',
        Runtime='python3.9',
        Role=labrole['Role']['Arn'],
        Handler='scale_up_lambda.scale_up_lambda',
        Code=dict(ZipFile=zipped_code), 
        MemorySize=3000,
    )

    lambda_client.add_permission(
        FunctionName='scale_up_lambda',
        StatementId='16',
        Action='lambda:InvokeFunction',
        Principal='events.amazonaws.com',
        SourceArn='arn:aws:events:us-east-1:'+str(account_number)+':rule/EC2HealthChange'
    )

    lambda_client.add_permission(
        FunctionName='scale_up_lambda',
        StatementId='21',
        Action='lambda:InvokeFunction',
        Principal='sqs.amazonaws.com',
        SourceArn='arn:aws:sqs:us-east-1:'+str(account_number)+':scaleUpLambdaQueue',
    )

# if running for the first time EVER ON ACCOUNT, uncomment this out --------------------------------------------------------------
    lambda_client.create_event_source_mapping(
        EventSourceArn='arn:aws:sqs:us-east-1:'+str(account_number)+':scaleUpLambdaQueue',
        FunctionName='scale_up_lambda',
        Enabled=True,
        BatchSize=10
    )
    
    # lambda_client.update_event_source_mapping(
    #     UUID = 'aba0b350-02c0-4ff1-84a0-a6fc6705eb4e',
    #     FunctionName='scale_up_lambda',
    #     Enabled=True,
    #     BatchSize=10
    # )
    
def create_split_work_lambda():
    with open('split_work_lambda.zip', 'rb') as f:
        zipped_code = f.read()

    labrole = iam_client.get_role(RoleName='LabRole')

    lambda_response = lambda_client.create_function(
        FunctionName='split-work-lambda',
        Runtime='python3.9',
        Role=labrole['Role']['Arn'],
        Handler='split_work_lambda.split_work_lambda',
        Code=dict(ZipFile=zipped_code),
        Layers=[
            'arn:aws:lambda:us-east-1:770693421928:layer:Klayers-p39-matplotlib:1',
        ], 
        MemorySize=3000,
        Timeout=300
    )

    lambda_client.add_permission(
        FunctionName='split-work-lambda',
        StatementId='14',
        Action='lambda:InvokeFunction',
        Principal='s3.amazonaws.com',
        SourceArn='arn:aws:s3:::client-upload-work-bucket'
    )
    
    s3_client.put_bucket_notification_configuration(
        Bucket="client-upload-work-bucket",
        NotificationConfiguration= 
        {
            'LambdaFunctionConfigurations':[
                {
                    'LambdaFunctionArn': lambda_response['FunctionArn'],
                    'Events': ['s3:ObjectCreated:*']
                }
            ]
        },
    SkipDestinationValidation = True
    )

launch_stitch_instance()
create_scale_up_lambda()
launch_ecs_example()
add_autoscale()
create_split_work_lambda()

