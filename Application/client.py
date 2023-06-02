import boto3
import sys
import os
import random
import re

ec2_resource = boto3.resource('ec2')
ec2_client = boto3.client('ec2')
s3_resource = boto3.resource('s3')
s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')
sqs_resource = boto3.resource(
    'sqs',
    endpoint_url="https://sqs.{}.amazonaws.com".format(
        os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    ),
)
sqs_client = boto3.client(
    'sqs',
    endpoint_url="https://sqs.{}.amazonaws.com".format(
        os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    ),
)


# listen to results queue ---------------------------------------------------------
def get_messages_from_queue(queue_url, numOfFiles, expectingFilenames):
    print("Client queue listening...")
    filesReturned = 0

    while True:
        resp = sqs_client.receive_message(
            QueueUrl=queue_url,
            AttributeNames=['All'],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5,
            VisibilityTimeout=20
        )
        
        messages = []
        try:
            messages = resp['Messages']
        except KeyError:
            print('No messages on the client queue')
            messages = []
            continue

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
        
        for message in messages:
            message_body = message['Body']

            fileName = message_body.split("-")[0]

            if(fileName in expectingFilenames):
                print(message_body)

                s3_client.download_file('client-results-bucket', f'{message_body}', f'{message_body}') 
                filesReturned+=1
                if(filesReturned == numOfFiles):
                    return 
            

if __name__ == "__main__":

    images_filenames = []
    numOfFiles = 0

    expectingFilenames = []

    if len(sys.argv) < 2:
        print("Please provide an image file")
    elif len(sys.argv) >= 2:
        images_filenames = sys.argv[1:]
        numOfFiles = len(sys.argv[1:])

    for image_name in images_filenames:
        pathname = os.path.basename(image_name)
        uniqueName = str(random.randint(10**12, 10**13-1))+pathname
        s3_client.upload_file(pathname, 'client-upload-work-bucket',  uniqueName)
        expectingFilenames.append(uniqueName[:-4])

    clientResultQueue = sqs_resource.get_queue_by_name(QueueName='clientResultQueue')
    get_messages_from_queue(clientResultQueue.url, numOfFiles, expectingFilenames)


