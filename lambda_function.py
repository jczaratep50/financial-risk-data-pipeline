import os
import json
import boto3
import logging
import pandas as pd
import numpy as np
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# S3 client initialization
s3_client = boto3.client('s3')

# Reed Environment Variables
PROCESSED_BUCKET = os.environ['PROCESSED_BUCKET']
CLEAN_PREFIX = os.environ['CLEAN_PREFIX']
ARCHIVE_PREFIX = os.environ['ARCHIVE_PREFIX']
ERROR_PREFIX = os.environ['ERROR_PREFIX']

# Constants
REQUIRED_COLUMNS = ['Exposure', 'PD']

def lambda_handler(event, context):

    logger.info("Financial Risk Pipeline Started")

    try:

        # Extract information from the file
        bucket_name = event['Records'][0]['s3']['bucket']['name']
        file_key = event['Records'][0]['s3']['object']['key']

        # Generate dynamic output filename
        original_filename = file_key.split('/')[-1]
        output_key = (f"{CLEAN_PREFIX}processed_{original_filename}")

        logger.info(f"Bucket: {bucket_name}")
        logger.info(f"File: {file_key}")

        # The object is obtained from S3
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)

        # The object is converted to a Pandas DataFrame
        df = pd.read_csv(response['Body'])

        logger.info(f"File read successfully")
        logger.info(f"Rows detected: {len(df)}")
        logger.info(f"Columns detected: {list(df.columns)}")

        # Validate required columns
        missing_columns = [
            col for col in REQUIRED_COLUMNS
            if col not in df.columns
        ]

        if missing_columns:

            logger.error(
                f"Missing required columns: {missing_columns}"
            )

            # Copy objects between folders in S3
            s3_client.copy_object(
                Bucket=PROCESSED_BUCKET,
                CopySource={'Bucket': bucket_name, 'Key': file_key},
                Key=f"{ERROR_PREFIX}invalid_{original_filename}"
            )

            # Delete the object from the original folder
            s3_client.delete_object(Bucket=bucket_name, Key=file_key)

            raise ValueError(
                f"Missing required columns: {missing_columns}"
            )

        # Data processing is performed
        df = (
            df
            .assign(
                EL = lambda x: x['Exposure'] * x['PD'],
                Risk_Level = lambda x: np.select([x['EL'] < 1000, x['EL'] > 5000], ['LOW', 'HIGH'], default='MEDIUM')
            )
        )

        logger.info("Financial calculations completed")
        logger.info(f"Output file: {output_key}")

        # Export Data Frame to CSV
        csv_buffer = df.to_csv(index=False)

        # Upload processed csv to S3
        s3_client.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=output_key,
            Body=csv_buffer
        )

        # Copy objects between folders in S3
        s3_client.copy_object(
            Bucket=bucket_name,
            CopySource={'Bucket': bucket_name, 'Key': file_key},
            Key=f"{ARCHIVE_PREFIX}{original_filename}"
        )

        # Delete the object from the original folder
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)

        logger.info("Processed file uploaded successfully")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Processing completed successfully',
                'source_file': file_key,
                'output_file': output_key,
                'rows_processed': len(df)
            })
        }

    except ClientError as e:

        logger.error(
            f"AWS ClientError while processing file: {str(e)}"
        )

        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }

    except ValueError as e:

        logger.error(
            f"Validation error: {str(e)}"
        )

        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': str(e)
            })
        }

    except Exception as e:

        logger.error(
            f"Unexpected error: {str(e)}"
        )

        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }

