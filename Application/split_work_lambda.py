import boto3
import os
import matplotlib.image as img
import json

AWS_REGION = "us-east-1"

sqs_resource = boto3.resource('sqs',endpoint_url="https://sqs.{}.amazonaws.com".format(os.environ.get("AWS_DEFAULT_REGION", "us-east-1")))
s3_client = boto3.client("s3", region_name=AWS_REGION)
s3_resource = boto3.resource('s3',region_name=AWS_REGION)
ecs_client = boto3.client("ecs", region_name=AWS_REGION)
ec2_client = boto3.client("ec2", region_name=AWS_REGION)

cluster_name = "BotoCluster"

def split_work_lambda(event, context):
    workQueue = sqs_resource.get_queue_by_name(QueueName='workQueue')
    scaleUpLambdaQueue = sqs_resource.get_queue_by_name(QueueName='scaleUpLambdaQueue')
    splitCount = 6

    if ( not os.path.exists('/tmp/files')):
        os.mkdir('/tmp/files')
    file_name = event['Records'][0]['s3']['object']['key']
    s3_client.download_file('client-upload-work-bucket', f'{file_name}', f'/tmp/files{file_name}')
    
    json_object = {
        "chunk_details": []
    }

    s3_client.put_object(
        Body=json.dumps(json_object),
        Bucket='stitch-count-lambda-bucket',
        Key=f'{file_name[:-4]}.json'
    )

    m = img.imread('/tmp/files'+file_name)

    w, h = m.shape[:2]

    if (h >1000):
        splitCount = 12
        
    split = int(h/splitCount)

    for i in range(splitCount):
        start = i*split
        end = (i+1)*split
        chunk = (m[0:w, start:end])

        chunk_filename = f"{file_name[:-4]}-{i}-{splitCount}.png"
        img.imsave('/tmp/files/'+chunk_filename, chunk)
        s3_resource.Bucket('split-work-bucket').upload_file('/tmp/files/'+chunk_filename, chunk_filename)
        workQueue.send_message(MessageBody=chunk_filename)

    scaleUpLambdaQueue.send_message(MessageBody="work")
        
