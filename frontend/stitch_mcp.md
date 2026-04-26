3. Configure the Project & Permissions
Select your working project and enable the Stitch API. You must also grant your user permission to consume services.

Terminal window
# Replace [YOUR_PROJECT_ID] with your actual Google Cloud Project ID
PROJECT_ID="[YOUR_PROJECT_ID]"

gcloud config set project "$PROJECT_ID"

# Enable the Stitch API
gcloud beta services mcp enable stitch.googleapis.com --project="$PROJECT_ID"

# Grant Service Usage Consumer role
USER_EMAIL=$(gcloud config get-value account)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="user:$USER_EMAIL" \
    --role="roles/serviceusage.serviceUsageConsumer" \
    --condition=None

4. Generate the Secrets (.env)
Finally, we generate the Access Token and save it to a .env file.

This overwrites any existing .env file

Terminal window
# Print the token
TOKEN=$(gcloud auth application-default print-access-token)

# Note: This overwrites any existing .env file
echo "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" > .env
echo "STITCH_ACCESS_TOKEN=$TOKEN" >> .env

echo "Secrets generated in .env"

5. Keeping it Fresh
Note: Access Tokens are temporary (usually lasting 1 hour). When your MCP client stops responding or says “Unauthenticated,” you need to:

Re-run the commands in Step 4 to update your .env file
Copy the new STITCH_ACCESS_TOKEN value from .env into your MCP client config file
Most MCP clients don’t automatically read from .env files, so you’ll need to manually update the token in your config file each time it expires.

Setting up your MCP Client
Copy the values from your .env file into your MCP client configuration. Replace the placeholders below with the actual values from your .env file:

<YOUR_PROJECT_ID> → Value of GOOGLE_CLOUD_PROJECT from .env
<YOUR_ACCESS_TOKEN> → Value of STITCH_ACCESS_TOKEN from .env
[!IMPORTANT] You will need to manually update the Authorization header in your config file every hour when the access token expires. See Step 5 above for the refresh workflow.

Cursor
