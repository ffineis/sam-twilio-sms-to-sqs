import base64
import os
import json
import boto3
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from urllib.parse import parse_qs


SECRETS_CLIENT = boto3.client("secretsmanager")
SQS_CLIENT = boto3.client("sqs")


def send_sms(body: str, recipient: str, sender: str, account_sid: str, auth_token: str) -> None:
    """
    Send an SMS message using the Twilio API.

    Args:
        body: str, required, the text of the message.
        recipient: str, required, the phone number to send the message to.
        sender: str, required, the phone number to send the message from.
        account_sid: str, required, the Twilio account SID.
        auth_token: str, required, the Twilio auth token.
    """
    client = Client(account_sid, auth_token)

    # -- send a response using the Twilio API
    response = client.messages.create(
        body=body,
        from_=sender,
        to=recipient
    )


def load_twilio_secrets(secret_name: str) -> dict:
    """
    Load Twilio secrets from AWS Secrets Manager.
    Requires that the secret contains the following secret strings:
    "TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID"

    Args:
        secret_name: str, required, the name of the secret in AWS Secrets Manager.
    Returns:
        dict[str, str], Twilio secrets.
    """
    response = SECRETS_CLIENT.get_secret_value(SecretId=secret_name)
    secrets = json.loads(response["SecretString"])
    secret_names = ["TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID"]
    assert all(secret_name in secrets for secret_name in secret_names), "Missing Twilio secrets."
    return secrets


def get_event_body(event: dict) -> dict:
    """
    Extract the body from the Lambda event, which may be base64 encoded, and
    parse it into a dictionary. Must use `keep_blank_values=True` because Twilio signature verification
    requires that the full POST payload match exactly what Twilio had sent.

    Read more:
        - https://www.twilio.com/docs/usage/security#validating-requests
        - https://stackoverflow.com/questions/77584306/unable-to-validate-twilio-incoming-sms-webhook-with-aws-lambda
    """
    if event.get("isBase64Encoded", False):
        body_str = base64.b64decode(event["body"]).decode("utf-8")
    else:
        body_str = event["body"]

    body_dict = parse_qs(body_str, keep_blank_values=True)
    json_body = {k: v[0] for k, v in body_dict.items()}
    return json_body


def validate_sms_from_twilio(event: dict, auth_token: str) -> bool:
    """
    Verify that the incoming SMS message was sent from Twilio by generating a signature
    and comparing it to the signature provided in the event headers.
    """
    validator = RequestValidator(auth_token)
    post_vars = get_event_body(event)
    url = "https://" + event["headers"]["host"] + event["requestContext"]["http"]["path"]
    twilio_signature = event["headers"]["x-twilio-signature"]
    return validator.validate(url, post_vars, twilio_signature)


def lambda_handler(event, context):
    """
    Field a Twilio SMS message sent to the API Gateway endpoint to which this Lambda is attached.
    Add the API Gateway endpoint as the webhook URL in the Twilio console for your SMS phone number.

    1. Validate that the text message was sent to this Lambda from Twilio.
        - If message not from Twilio, respond with 400 error.
    2. Post successful validation, send the message to an SQS queue for downstream processing.

    Args:
        event: dict, required
            API Gateway Lambda Proxy Input Format
            Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format
    """

    secrets = load_twilio_secrets("twilio-sms-to-sqs")
    try:
        # -- validate the request
        if not validate_sms_from_twilio(event, auth_token=secrets["TWILIO_AUTH_TOKEN"]):
            return {"statusCode": 400, "body": "Could not validate Twilio signature."}
    except Exception as e:
        print(f"Exception: {e}")
        return {"status_code": 500, "body": "Encountered exception while trying to validate Twilio event."}

    # -- extract the message and sender info from the event
    message_data = get_event_body(event)
    from_number = message_data["From"]
    twilio_phone_number = message_data["To"]
    message_text = message_data["Body"]

    sqs_message = {
        "from": from_number,
        "to": twilio_phone_number,
        "text": message_text
    }

    # -- send message to SQS
    queue_url = os.environ.get("SQS_QUEUE_URL")
    SQS_CLIENT.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(sqs_message)
    )

    # -- respond TO number we received message FROM. (just a test).
    # send_sms(body="Hi from twilio!", recipient=from_number, sender=twilio_phone_number,
    #          account_sid=secrets["TWILIO_ACCOUNT_SID"], auth_token=secrets["TWILIO_AUTH_TOKEN"])

    return {"status_code": 200, "body": f"Hello from {from_number}! Received: {message_text}"}
