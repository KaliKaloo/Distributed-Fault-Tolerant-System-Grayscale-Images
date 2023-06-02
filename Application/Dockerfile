FROM python:3.9

USER root

ADD singleWorker.py .

RUN pip install numpy matplotlib boto3

CMD ["python" , "./singleWorker.py"]

