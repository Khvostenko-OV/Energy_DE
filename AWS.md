# AWS. Event driven ETL

## 1. Data source
- Project deployed on AWS ec2 instance under Ubuntu 26  
- All .gpkg files landed in AWS s3 bucket
- Boundaries files stored in their own folder from the very beginning
- Link to boundaries folder leaves in .env
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

### The message contract (issue #6)
- The worker receives **one** SQS message at a time (long polling) and decodes every S3 record it carries. Separate messages are never combined, because one message is also one acknowledgement
- Within a message the order is fixed: Boundary records first as a single release, then Source records. Source rows are enriched with Boundary geography, so the release has to be applied first
- Records are processed independently: each one is its own Ingestion run with its own result, and a failing record never blocks the others in the same message
- The geography rebuild and the three materialized views are refreshed **once** per message, after the last record
- The message is deleted only when every record is successful, terminally skipped, or stale. If one record is still retryable the message stays, and redelivery processes only the records that are not settled yet
- Every failure is retryable today, including a deterministically invalid file; retries, DLQ redrive, and SNS alerts are issue #7. The topic is read from `SNS_TOPIC_ARN` and the queue from `SQS_QUEUE_URL`, the bucket from `S3_BUCKET`

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