import numpy as npy
import matplotlib.image as img
from statistics import mean
import boto3
s3_resource = boto3.resource('s3', region_name="us-east-1" )
s3_client = boto3.client('s3', region_name="us-east-1" )
sqs_resource = boto3.resource("sqs", region_name="us-east-1")
sqs_client = boto3.client("sqs", region_name="us-east-1"  )

workQueue = sqs_resource.get_queue_by_name(QueueName="workQueue")

def turnChunkGray(fileName):
    m = img.imread(f'{fileName}')    
    w, h = m.shape[:2]
    newImage = npy.zeros([w, h, 4])


    for i in range(w):
        for j in range(h):
            # ratio of RGB will be between 0 and 1
            lst = [float(m[i][j][0]), float(m[i][j][1]), float(m[i][j][2])]
            avg = float(mean(lst))
            newImage[i][j][0] = avg
            newImage[i][j][1] = avg
            newImage[i][j][2] = avg
            newImage[i][j][3] = 1 # alpha value to be 1

    grayImageName = f'{fileName}'
    print(grayImageName)
    img.imsave(grayImageName, newImage)
    return grayImageName

def get_messages_from_queue(queue_url):
    while True:
        resp = sqs_client.receive_message(
            QueueUrl=queue_url,
            AttributeNames=['All'],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5,
            VisibilityTimeout=60
        )
        
        messages = []
        try:
            messages = resp['Messages']
        except KeyError:
            print('No messages on the queue!')
            messages = []
            continue

        
        for message in messages:
            message_body = message['Body']
            s3_client.download_file('split-work-bucket', f'{message_body}', f'{message_body}')
            
            # turn image grayscale
            result = turnChunkGray(message_body)

            s3_resource.Bucket('split-results-bucket').upload_file(result, result)

            splitResultQueue = sqs_resource.get_queue_by_name(QueueName='splitResultQueue')
            splitResultQueue.send_message(MessageBody=result)
        
        entries = [
            {'Id': msg['MessageId'], 'ReceiptHandle': msg['ReceiptHandle']}
            for msg in resp['Messages']
        ]

        resp = sqs_client.delete_message_batch(
            QueueUrl=queue_url, Entries=entries
        )

        if len(resp['Successful']) != len(entries):
            raise RuntimeError(
                f"Failed to delete messages: entries={entries!r} resp={resp!r}"
            )


get_messages_from_queue(workQueue.url)
