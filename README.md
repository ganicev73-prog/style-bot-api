Backend bundle for deploying the Mini App API to Render.

Files in this folder are a deployment snapshot assembled from the main project.

What to do:

1. Create a new GitHub repository, for example `neural-style-backend`.
2. Upload the contents of this folder to that repository root.
3. In Render, create a `Web Service` from that repository.
4. Set environment variables there instead of committing secrets.

Do not commit real `.env`, `users.db`, logs, backups, or results.

Suggested Render settings:

- Build Command: `pip install -r requirements.txt`
- Start Command: `python3 -u web_api.py`

Required env vars:

- `WEB_API_HOST=0.0.0.0`
- `WEB_API_PORT=10000`
- `BOT_USERNAME=NeuralStyleTransferBot`

Optional env vars depending on your setup:

- `BOT_TOKEN`
- `ADMIN_ID`
- `CRYPTO_CLOUD_API_KEY`
- `CRYPTO_CLOUD_SHOP_ID`
- `WEB_APP_URL`
- `WEB_API_PUBLIC_URL`
