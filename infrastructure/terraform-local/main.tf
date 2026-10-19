# A separate S3 bucket managed by Terraform
resource "aws_s3_bucket" "energy_test" {
  bucket = "energy-demo-terraform-test"

  tags = {
    Project     = "EnergyDemo"
    Environment = "Local"
    ManagedBy   = "Terraform"
  }
}


# Python Lambda managed by Terraform
resource "aws_lambda_function" "energy" {
  function_name = "energy-demo-terraform-function"

  # Python deployment package
  filename         = "../../lambda/energy/energy-lambda.zip"
  source_code_hash = filebase64sha256("../../lambda/energy/energy-lambda.zip")

  # Lambda configuration
  handler = "handler.lambda_handler"
  runtime = "python3.12"

  # Local Floci testing role
  role = "arn:aws:iam::000000000000:role/energy-demo-lambda-role"

  timeout     = 10
  memory_size = 128

  tags = {
    Project     = "EnergyDemo"
    Environment = "Local"
    ManagedBy   = "Terraform"
  }
}
