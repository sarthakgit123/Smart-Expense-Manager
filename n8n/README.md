# n8n workflow – Telegram bot for Smart Expense Manager

`telegram_expense_workflow.json` is an importable n8n workflow that connects a
Telegram bot to the Django app:

```
Telegram ──► [Telegram Trigger] ─► [Config] ─► [Show typing…] ─► [Send to Django] ─┬─► [Reply]               (reply_text from Django)
                                                                  POST /api/telegram/  └─► [Reply: server error] (Django down / 4xx / 5xx after 3 tries)
                                                                  message/
```

n8n does not parse anything. It forwards the message, and Django returns a
ready-to-send `reply_text`. To change what the bot understands, edit
`transactions/telegram_parser.py` and redeploy Django. The workflow stays the
same.

The JSON contains **no secrets**. The bot token and the shared secret go into
n8n **credentials**, which n8n stores encrypted.

---

## 1. Create the bot (Telegram, about 3 minutes)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Choose a display name and a username ending in `bot`. The username goes into
   Django's `TELEGRAM_BOT_USERNAME` without the `@`.
3. BotFather replies with a **bot token**. Treat it like a password: never
   commit it, paste it in chat, or put it in a workflow field. It only goes
   into the n8n credential in step 3.
4. Optional: send `/setcommands`, choose the bot, and paste:
   ```
   summary - This month's income & expenses
   budget - Budget usage this month
   recent - Last 5 transactions
   categories - Categories you can use
   undo - Delete the last transaction added here
   help - How to log expenses
   ```

## 2. Choose where n8n runs

The Telegram Trigger needs a **public HTTPS URL**, because Telegram pushes
messages to n8n.

| Option | When to use it | Notes |
| --- | --- | --- |
| **n8n Cloud** | Easiest, always on | Calls your deployed Django (Render). |
| **Self-hosted (Docker) on a server** | Free or cheap, always on | Set `WEBHOOK_URL=https://your-n8n-domain/` so n8n registers the correct URL with Telegram. |
| **Local Docker + tunnel** | Testing only | Run `cloudflared tunnel --url http://localhost:5678` (or ngrok) and set `WEBHOOK_URL` to the tunnel URL. Django can run locally too: use `http://host.docker.internal:8000` as `django_base_url`. |

Whichever option you choose, the Django it calls must run the code from
Phases 1 and 2, with migrations applied.

## 3. Create two credentials in n8n

Go to **Credentials → Add credential**:

| Credential type | Name (must match the workflow) | Fields |
| --- | --- | --- |
| **Telegram API** | `Smart Expense Telegram Bot` | Access Token: the BotFather token |
| **Header Auth** | `Smart Expense n8n secret` | Name: `X-N8N-Secret` · Value: the **same** value as Django's `N8N_WEBHOOK_SECRET` |

Generate the shared secret once and paste it in **both** places (Render
environment and the n8n credential):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 4. Import and configure the workflow

1. Go to **Workflows → Import from File** and choose
   `n8n/telegram_expense_workflow.json`.
2. Open each Telegram node and the **Send to Django** node, and choose the
   credential from step 3. Imported credential links are blank on purpose.
3. Open **Config** and set `django_base_url` to your Django site, without a
   trailing slash (for example `https://finance-tracker-0oc7.onrender.com`).
4. **Save**, then turn the workflow **Active**. n8n registers the Telegram
   webhook automatically.

> A bot can have only **one** webhook. While you click **Test workflow**, n8n
> temporarily points Telegram at the test URL. When you finish testing,
> activate the workflow so the production URL is registered again. Don't run
> two workflows with the same bot token.

## 5. Django environment

```env
N8N_WEBHOOK_SECRET=<same value as the n8n Header Auth credential>
TELEGRAM_BOT_USERNAME=<bot username without @>
TELEGRAM_LINK_CODE_TTL_MINUTES=10
TIME_ZONE=Asia/Kolkata
```

### On Vercel

1. Go to **Project → Settings → Environment Variables** and add the four
   variables above for **Production** (and Preview, if you test there). Values
   are read only at deploy time, so **redeploy** after adding or changing them.
2. **Vercel doesn't run migrations.** `vercel.json` only builds
   `api/index.py`. Whenever a new migration exists, run it once from your PC
   against the same Neon database Vercel uses (the `DATABASE_URL` in your local
   `.env`), and do *not* set `USE_SQLITE`:
   ```powershell
   python manage.py migrate
   ```
3. **Point n8n at the production domain**, for example
   `https://your-project.vercel.app`. Pushes to a non-production branch create
   **Preview** deployments, which Vercel's *Deployment Protection* hides behind
   a Vercel login. n8n's calls to them get a 401 HTML page and never reach
   Django. Either merge to the production branch (usually `main`), or
   temporarily add Vercel's *Protection Bypass for Automation* header for a
   preview.
4. Check that **Settings → Functions** allows enough time for the function
   (Max Duration). The bot request itself is quick, but an over-budget expense
   also sends the alert email over SMTP before replying.

### On Render

Set the same variables in the service's **Environment** tab. `build.sh` runs
`migrate` on every deploy.

## 6. Try it

1. On the website, open **✈️ Telegram**, click **Generate Link Code**, then
   **Link instantly**, and tap **Start** in Telegram. You should see
   `✅ Linked to …`.
2. Send `250 groceries`. You should see `✅ Expense of ₹250 logged`, and the
   expense should appear on the dashboard.
3. Try `/summary`, `/budget`, `/recent`, `/undo` and `hello` (a friendly
   "couldn't find an amount" reply).

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Bot never answers | The workflow isn't **Active**; n8n has no public HTTPS URL (`WEBHOOK_URL`); or another workflow or tool is using the same token. |
| "⚠️ Sorry, I couldn't reach the expense server" | Check the failed execution in n8n. A **401 with JSON `{"ok": false, "error": "Unauthorized"}`** means the `X-N8N-Secret` value differs from `N8N_WEBHOOK_SECRET` (or the variable was added without redeploying). A **401 or 403 HTML page from Vercel** means `django_base_url` is a protected Preview URL. A 404 means the wrong `django_base_url`, or a deployment without this code. A 500 often means a missing migration on Neon. |
| First message after a while is slow | Cold start (a few seconds on Vercel, 30–60 s on Render's free tier). The workflow shows "typing…" and retries; Django never logs a retried message twice. |
| "isn't linked yet" | Link again from the website. Codes expire after `TELEGRAM_LINK_CODE_TTL_MINUTES`. |

## Test without Telegram or n8n

`telegram_chat` sends the same JSON the workflow sends and prints the reply:

```powershell
$env:USE_SQLITE="True"; python manage.py telegram_chat --telegram-user-id 111
```

## Privacy

The workflow stores **failed** executions only (`saveDataSuccessExecution: none`),
so normal financial messages are not kept in n8n's execution history.
