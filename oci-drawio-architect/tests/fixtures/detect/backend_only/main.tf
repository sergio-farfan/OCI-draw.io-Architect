terraform {
  backend "s3" {
    bucket = "state"
    region = "us-east-1"
  }
}
