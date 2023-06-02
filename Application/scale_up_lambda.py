import boto3
import os
from datetime import datetime, timedelta

AWS_REGION = "us-east-1"

ec2_client = boto3.client('ec2', region_name=AWS_REGION)
ec2_resource = boto3.resource('ec2', region_name=AWS_REGION)
ecs_client = boto3.client("ecs", endpoint_url="https://ecs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
sqs_client = boto3.client('sqs',endpoint_url="https://sqs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
sqs_resource = boto3.resource('sqs',endpoint_url="https://sqs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
cloud_client = boto3.client('cloudwatch', region_name=AWS_REGION)
ssm_client = boto3.client('ssm')
s3_resource = boto3.resource('s3',region_name=AWS_REGION)

cluster_name = "BotoCluster"

def ec2_get_subnet_list():
    response = ec2_client.describe_subnets()
    return response['Subnets']

def launch_stitch_instance():
    user_data = '''#!/bin/bash
    aws s3 cp s3://stitch-python-bucket/stitch_image.py home/ec2-user/stitch_image.py
    sudo pip install numpy ; pip install matplotlib ; pip install boto3
    sudo python3 /home/ec2-user/stitch_image.py'''

    ec2_resource.create_instances(
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

def launch_first_instance(subnet1, default_sg):
    ec2_resource.create_instances(
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
def checkIfInstanceExists(tagName):
    print("in")
    response = ec2_client.describe_instances(
        Filters=[
            {
                'Name': 'tag:Name',
                'Values': [
                    tagName,
                ]
            },
            {
                'Name':'instance-state-name',
                'Values':[
                    'running'
                ]
            }
        ],
    )
    instancesArray = len(response["Reservations"])
    print(instancesArray)
    
    if instancesArray == 0:
        return True
    else:
        return False

def scale_up_lambda(event, context):
    print(event)
    subnet1 = ec2_get_subnet_list()[0]['SubnetId']
    default_sg = ec2_client.describe_security_groups(GroupNames=['default'])['SecurityGroups'][0]['GroupId']

    try:
        if(event["detail-type"]=="EC2 Instance State-change Notification"):
            instance_id = event["detail"]["instance-id"]
            response = ec2_client.describe_instances(
                InstanceIds=[
                    instance_id,
                ],
            )

            tagName = response["Reservations"][0]["Instances"][0]["Tags"][0]["Value"]
            
            if (tagName == "Stitch-instance"):
                print("tg name = stitch")
                if(checkIfInstanceExists(tagName)):
                    launch_stitch_instance()
            elif(tagName == "First-instance"):
                if(checkIfInstanceExists(tagName)):
                    launch_first_instance(subnet1, default_sg)
    except:
        print("Event type not: EC2 Instance State-change Notification")

    utc_now = datetime.now()
    numAttribute = cloud_client.get_metric_statistics(
        Namespace = 'AWS/SQS',
        MetricName = 'ApproximateNumberOfMessagesVisible',
        Dimensions = [
            {
                'Name': 'QueueName',
                'Value': 'workQueue',
            }
        ],
        StartTime = utc_now - timedelta(seconds=600),
        EndTime = utc_now,
        Period =600,
        Statistics = ['Maximum'],
        Unit = 'Count'
        )

    numInstances = ecs_client.list_container_instances(
        cluster=cluster_name,
        status='ACTIVE'
    )
    # print(numAttribute)

    if (numAttribute['Datapoints']):
        numOfMessages = int(numAttribute['Datapoints'][0]['Maximum'])
        numOfInstances = len(numInstances['containerInstanceArns'])
        print(numOfMessages)
        print(numInstances)
        if( float(numOfMessages/4) > float(numOfInstances) ):
            
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
                        'Value': 'ScaleUp-instance'
                    },]
            }   ,
            ]
            )
    
            print(instances[0].instance_id)
    
            for i, instance in enumerate(instances):
                # Create alarm
                cloud_client.put_metric_alarm(
                    AlarmName='EC2InstanceCPU<1' + instances[i].instance_id,
                    ComparisonOperator='LessThanOrEqualToThreshold',
                    EvaluationPeriods=3,
                    MetricName='CPUUtilization',
                    Namespace='AWS/EC2',
                    Period=300,
                    Statistic='Minimum',
                    Threshold=1,
                    ActionsEnabled=True,
                    AlarmActions=[
                        'arn:aws:automate:us-east-1:ec2:terminate',
                    ],
                    AlarmDescription='CPUUtilization <= 1 for 1 datapoints within 2 minutes',
                    Dimensions=[
                            {
                            'Name': 'InstanceId',
                            'Value': instances[i].instance_id,
                            }
                    ],
                    Unit='Percent'

                )