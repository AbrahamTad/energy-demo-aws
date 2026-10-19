# Local AWS simulator configuration
provider "aws" {
  region     = "eu-north-1"
  access_key = "test"
  secret_key = "test"

  # Prevent Terraform from contacting real AWS for validation
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  # Use S3 path-style addressing for Floci
  s3_use_path_style = true

  # Send AWS service requests to our local Floci instance
  endpoints {
    s3         = "http://127.0.0.1:4567"
    lambda     = "http://127.0.0.1:4567"
    apigateway = "http://127.0.0.1:4567"
    iam        = "http://127.0.0.1:4567"
    sts        = "http://127.0.0.1:4567"
  }
}
