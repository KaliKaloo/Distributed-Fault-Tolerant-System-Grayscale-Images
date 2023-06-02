import boto3
import os
import matplotlib.image as img
import numpy as np
import json

AWS_REGION = "us-east-1"

# ECS Details
ec2_client = boto3.client('ec2', region_name=AWS_REGION)
s3_client = boto3.client('s3',region_name=AWS_REGION)
s3_resource = boto3.resource('s3',region_name=AWS_REGION)
sqs_resource = boto3.resource("sqs", region_name=AWS_REGION)
sqs_client = boto3.client("sqs", region_name=AWS_REGION)

def stitch_work(chunks_array, jsonName):
    # define a sort key
    def sort_key(chunk):
        return int(chunk[1])

    # sort by 
    chunks_array.sort(key=sort_key)
    chunk_img = []
    for i, c in enumerate(chunks_array):
        chunk_filename = "-".join(chunks_array[i])
        s3_client.download_file('split-results-bucket', chunk_filename, chunk_filename)
        chunk_img.append(img.imread(chunk_filename))
    
    chunk_tuple = tuple(chunk_img)

    image = np.hstack(chunk_tuple)

    result_gray = f'{chunks_array[0][0]}-grayed.png'
    img.imsave(result_gray, image)

    # upload gray image and send message to client
    s3_resource.Bucket('client-results-bucket').upload_file(result_gray, result_gray)
    clientResultQueue = sqs_resource.get_queue_by_name(QueueName='clientResultQueue')
    clientResultQueue.send_message(MessageBody=result_gray)
    
    s3_client.delete_object(
        Bucket='stitch-count-lambda-bucket', 
        Key=f'{jsonName}.json'
    )
    
    for i, c in enumerate(chunks_array):
        chunk_filename = "-".join(chunks_array[i])
        os.remove(chunk_filename)
    os.remove(result_gray)

    return

def get_messages_from_queue(queue_url):
    while True:
        resp = sqs_client.receive_message(
            QueueUrl=queue_url,
            AttributeNames=['All'],
            MaxNumberOfMessages=10,
            WaitTimeSeconds=5
        )
        
        messages = []
        try:
            messages = resp['Messages']
        except KeyError:
            print('No messages on the queue!')
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
            
            chunk_details = message_body.split("-")

            jsonName = chunk_details[0]
            splitCount = int(chunk_details[-1].split('.')[0])

            data = s3_client.get_object(Bucket='stitch-count-lambda-bucket', Key=f'{jsonName}.json')
            json_text_bytes = data["Body"].read().decode("utf-8")
            json_text = json.loads(json_text_bytes)

            json_text["chunk_details"].append(chunk_details)

            s3_client.put_object(
            Body=json.dumps(json_text),
            Bucket='stitch-count-lambda-bucket',
            Key=f'{jsonName}.json'
            )

            if ( len(json_text["chunk_details"]) == splitCount):
                chunks_array = json_text["chunk_details"]
                stitch_work(chunks_array, jsonName)


if __name__ == "__main__":
    splitResultQueue = sqs_resource.get_queue_by_name(QueueName='splitResultQueue')
    get_messages_from_queue(splitResultQueue.url)
