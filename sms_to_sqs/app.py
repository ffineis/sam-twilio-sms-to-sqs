import os
import json
import boto3
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from urllib.parse import urlencode


def send_sms(body: str, recipient: str) -> None:
    client = Client(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))

    # -- send a response using the Twilio API
    response = client.messages.create(
        body=body,
        from_=os.environ.get("TWILIO_PHONE_NUMBER"),
        to=recipient
    )


def lambda_handler(event, context):
    """
    Field Twilio SMS messages.

    1. Validate that the text message was sent to this Lambda from Twilio.
        - If message not from Twilio, respond with 400 error.
    2. Post successful validation, send the message to an SQS queue for downstream processing.

    Args:
        event: dict, required
            API Gateway Lambda Proxy Input Format

            Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format

        context: object, required
            Lambda Context runtime methods and attributes

            Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
        dict: contains "status_code" and "body" attributes.
    ------
    API Gateway Lambda Proxy Output Format: dict

        Return doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
    """
    print("Received event and context:")
    print(f"Event: {event}"
          f"context: {context}")

    try:
        validator = RequestValidator(os.environ.get("TWILIO_AUTH_TOKEN"))

        # -- prepare the data for validation
        url = "https://" + event["headers"]["Host"] + event["requestContext"]["path"]
        twilio_signature = event["headers"]["X-Twilio-Signature"]
        post_vars = event["body"]

        # -- validate the request
        if not validator.validate(url, post_vars, twilio_signature):
            return {"statusCode": 400, "body": "Invalid signature"}
    except Exception as e:
        print(f"Exception: {e}")
        return {"status_code": 500, "body": "Encountered exception while trying to validate Twilio event."}

    # -- extract the message and sender info from the event
    message_data = json.loads(event["body"])
    from_number = message_data["From"]
    to_number = message_data["To"]
    # print(f"\nto_number = {to_number}... twilio phone number = {os.environ.get('TWILIO_PHONE_NUMBER')}")
    message_text = message_data["Body"]

    sqs_message = {
        "raw": message_data,
        "from": from_number,
        "to": to_number,
        "text": message_text
    }

    # -- send message to SQS
    queue_url = os.environ.get("SQS_QUEUE_URL")
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(sqs_message)
    )

    # -- respond TO number we received message FROM. (just a test).
    # send_sms(body="Hi from twilio!", recipient=from_number)

    return {"status_code": 200, "body": f"Hello from {from_number}! Received: {message_text}"}
