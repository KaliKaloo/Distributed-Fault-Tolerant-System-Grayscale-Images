# A Distributed Fault Tolerant System - Turning Images Grayscale
## Prerequisites
- boto3 
- python
- configure aws credentials

## Deployment Instructions
### Prerequisites
- An AWS account
- `Python 3.7+`
- `boto3`
- `awscli`

### Setup
1. Create SQS and S3 endpoints for your VPC ![alt text](https://github.com/ccdb-uob/CW22-57/blob/main/images/endpoints.jpg "Logo Title Text 1")
2. Make sure you have IAM LabRole at https://console.aws.amazon.com/iam/home?region=us-west-1#/roles
3. Create a AWS Log Group and name it /ecs/ContainerLogGroup

### Execute
Go into the directory 'Application'
To start up the application, execute this command
```python
python startup.py
```
To use the application execute this command
```python
python client.py {path to image}
```
You can provide multiple images to the program, separated by spaces. For example:
```python
python client.py test_images/taj.png test_images/dice.png
```
Some test images are provided in the folder test_images. 

## Contributors
- Pragya Gurung
- Linda Lomenčíková

