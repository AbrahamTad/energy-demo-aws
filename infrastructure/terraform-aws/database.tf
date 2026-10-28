# Separate tables and Lambda roles: user content is never published automatically.
resource "aws_dynamodb_table" "public_energy" {
  name                        = "${local.name}-public-energy"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "dataset"
  range_key                   = "source"
  deletion_protection_enabled = true
  lifecycle { prevent_destroy = true }
  attribute {
    name = "dataset"
    type = "S"
  }
  attribute {
    name = "source"
    type = "S"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  on_demand_throughput {
    max_read_request_units  = 10
    max_write_request_units = 5
  }
}

resource "aws_dynamodb_table" "user_energy" {
  name                        = "${local.name}-user-energy"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "user_sub"
  range_key                   = "record_id"
  deletion_protection_enabled = true
  lifecycle { prevent_destroy = true }
  attribute {
    name = "user_sub"
    type = "S"
  }
  attribute {
    name = "record_id"
    type = "S"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  on_demand_throughput {
    max_read_request_units  = 10
    max_write_request_units = 5
  }
}

output "public_energy_table" { value = aws_dynamodb_table.public_energy.name }
output "user_energy_table" { value = aws_dynamodb_table.user_energy.name }
