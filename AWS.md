# AWS. Event driven ETL

## 1. Data source
- All .gpkg files are landed in AWS S3 bucket
- Boundaries files stored in their own folder from the very beginning
- Boundaries extraction strats with *docker compose up* 
- Source files are additionally loaded

## 2. Event driven workflow
- When source file appears in source/ folder, S3 Event Notification triggers ETL
- ETL-worker runs constantly
- Event s3:ObjectCreated goes to SQS + DLQ
- ETL-worker loads file from s3 to /tmp folder, after finishing ETL erases it.
- Energy source resolves through energy_source column in dataframe (not through filename) 
- Transform stage receives table name to transform. 
- All files are treated consequently via SQS 
- All extracted files are logged in loaded_files table and not extracted twice.

## 3. Logging
- All ETL logs are sent to CloudWatch Logs

## 4. Notifications
- Errors in ETL trigger SNS-alert with email subscription
- CloudWatch Alarm on DLQ → SNS

## 5. IAM role for EC2
- s3:GetObject, sqs:ReceiveMessage, DeleteMessage, ChangeMessageVisibility, GetQueueAttributes,
sns:Publish; logs:CreateLogStream, logs:PutLogEvents

## 6. Terraform
- Use Terraform for scripting