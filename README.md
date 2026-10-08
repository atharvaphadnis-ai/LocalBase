# LocalBase



https://github.com/user-attachments/assets/9879b0a3-1c2a-4f38-b2e8-c2eb4c533917



### Your self-hosted backend. Simple, local, and yours.

**LocalBase** is a lightweight, self-hosted backend platform built entirely with Python, FastAPI, and SQLite.

It gives developers a simple way to create projects, manage databases, edit records, execute SQL, expose REST APIs, generate API keys, create backups, import/export data, and monitor requests — all from a single Python application.

No hosted account is required.

No Node.js project is required.

No external database server is required.

Run LocalBase and you have your own backend.

---

## ✨ Features

* 🗄️ SQLite-powered databases
* 📁 Multiple independent projects
* 🖥️ Beautiful web dashboard
* 🌙 Dark and light themes
* 🧱 Visual table management
* 📝 SQL editor
* 🔌 REST API
* 🔑 API key management
* 📡 WebSocket events
* 📊 Database introspection
* 📋 Spreadsheet-style data editor
* 🔍 Filtering, sorting and pagination
* 💾 Database backups
* 📥 CSV import
* 📤 CSV and JSON export
* 📜 Request logs
* 💻 CLI
* 📖 Automatic FastAPI/OpenAPI documentation
* 🌐 LAN and self-hosted deployment
* ☁️ Compatible with reverse proxies and Cloudflare Tunnel
* 📦 Single-file Python application
* 🪶 Lightweight architecture
* 🐍 Pure Python backend
* 🔓 Open source

---

# Why LocalBase?

Modern backend platforms are powerful, but many applications don't need a large cloud infrastructure.

Sometimes you simply want:

```text
Your computer
     ↓
LocalBase
     ↓
SQLite
     ↓
Your application
```

LocalBase is designed around that idea.

You can run it locally during development, on a LAN for an IoT project, or on a server and expose it to the internet through your preferred reverse proxy or tunnel.

Your database files remain under your control.

---

# Architecture

LocalBase uses a simple architecture:

```text
                 ┌─────────────────────┐
                 │    Your Website     │
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │    REST API         │
                 │     FastAPI         │
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │      SQLite         │
                 │     Database        │
                 └─────────────────────┘

                 ┌─────────────────────┐
                 │   LocalBase Web UI  │
                 └──────────┬──────────┘
                            │
                            ▼
                       Same REST/API
```

The management dashboard and external applications communicate with the same LocalBase backend.

---

# 🧰 Technology

LocalBase currently uses:

* **Python**
* **FastAPI**
* **Uvicorn**
* **SQLite**
* **Pydantic**
* **HTML**
* **CSS**
* **Vanilla JavaScript**

The dashboard is embedded directly into the Python application, keeping the project extremely portable.

The current application identifies itself as **LocalBase 1.0.0** and is designed to run with:

```bash
python localbase.py
```

The application itself handles its data directory and creates the required project and backup directories automatically.

---

# 🚀 Getting Started

## Requirements

You need:

* Python 3.11+ recommended
* pip
* A supported operating system

LocalBase itself does not require Node.js, npm, React, Electron, or a separate database server.

---

# Installation

Clone the repository:

```bash
git clone https://github.com/atharvaphadnis-ai/localbase.git
cd localbase
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Then start LocalBase:

```bash
python localbase.py
```

By default, LocalBase starts on:

```text
http://127.0.0.1:8000
```

Open that address in your browser.

---

# 🎯 First Run

When LocalBase starts, it displays the following important endpoints:

```text
Dashboard:
http://127.0.0.1:8000

API:
http://127.0.0.1:8000/api

OpenAPI:
http://127.0.0.1:8000/docs

ReDoc:
http://127.0.0.1:8000/redoc
```

The server's startup configuration supports custom host, port, and data directory settings.

---

# 📁 Data Storage

LocalBase automatically creates a data directory.

The default structure is approximately:

```text
localbase-data/
│
├── localbase-meta.db
│
├── projects/
│   ├── myapp.db
│   ├── website.db
│   └── iot.db
│
└── backups/
    ├── myapp-20261007-120000.db
    └── iot-20261007-130000.db
```

The metadata database stores LocalBase's internal information such as:

* Projects
* API keys
* Request logs
* Saved SQL queries

Each project receives its own SQLite database file.

This gives projects a useful degree of database isolation.

---

# 🗂️ Projects

A LocalBase project represents an independent SQLite database.

For example:

```text
my-website
```

could contain:

```text
users
posts
comments
```

while:

```text
my-iot
```

could contain:

```text
devices
sensor_data
alerts
```

Projects can be created, listed, renamed, and deleted.

---

# Create a Project From the Dashboard

Open LocalBase and select:

```text
+ New Project
```

Enter the project ID/name.

Example:

```text
iot-monitor
```

LocalBase creates the corresponding SQLite database automatically.

---

# Create a Project From the CLI

You can also create projects without opening the dashboard:

```bash
python localbase.py create-project iot-monitor
```

List projects:

```bash
python localbase.py list-projects
```

---

# 🗄️ Database Management

After selecting a project, LocalBase provides a database interface.

You can inspect:

* Tables
* Row counts
* Columns
* Data types
* Primary keys
* Foreign keys
* Indexes

The database page is based on the actual SQLite schema rather than hard-coded demo data.

---

# 🧱 Creating Tables

Tables can be created through the LocalBase interface or through SQL.

Example:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

LocalBase supports common SQLite-compatible types including:

```text
TEXT
INTEGER
REAL
BLOB
NUMERIC
BOOLEAN
DATE
DATETIME
JSON
```

---

# ✏️ Managing Columns

The table structure interface allows you to inspect columns and add or remove columns.

Supported column information includes:

* Column name
* Type
* Primary key
* Nullable
* Default value

For example:

```text
id          INTEGER     PK
name        TEXT        NOT NULL
email       TEXT
created_at  DATETIME
```

LocalBase performs validation before modifying the schema.

---

# 🔗 Foreign Keys

LocalBase enables SQLite foreign-key enforcement for project database connections.

For example:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

The table structure interface can display detected foreign-key relationships.

---

# 📊 Data Editor

Open a table and select:

```text
Data
```

You get a table-style interface for viewing records.

You can:

* Add records
* Edit cells
* Delete records
* Refresh records
* Export data
* View row counts

Example:

```text
┌────┬──────────┬────────────────────┐
│ ID │ Name     │ Email              │
├────┼──────────┼────────────────────┤
│ 1  │ Atharva  │ atharva@example... │
│ 2  │ Alex     │ alex@example.com   │
└────┴──────────┴────────────────────┘
```

---

# 🔍 Filtering

The REST API supports filtering using query parameters.

Simple filtering:

```text
?name=Atharva
```

Operator-based filtering:

```text
?filter[age][gt]=18
```

Available operators include:

```text
eq
neq
gt
gte
lt
lte
like
in
```

---

# ↕️ Sorting

Sort by a column:

```text
?sort=created_at
```

Descending:

```text
?sort=created_at&order=desc
```

---

# 📄 Pagination

Limit the number of records returned:

```text
?limit=50
```

Skip records:

```text
?offset=50
```

LocalBase also caps normal REST queries at a maximum limit of 1000 records per request.

---

# ⌨️ SQL Editor

The SQL Editor is one of LocalBase's main features.

Open:

```text
SQL Editor
```

You can enter normal SQLite SQL.

Example:

```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL
);
```

Click:

```text
Run
```

Or use:

```text
Ctrl + Enter
```

---

# 🔎 SELECT Queries

Example:

```sql
SELECT * FROM products;
```

LocalBase displays the returned columns and records in a table.

It also reports:

* Number of rows
* Execution time

---

# ✏️ INSERT / UPDATE / DELETE

You can execute normal SQL:

```sql
INSERT INTO products (name, price)
VALUES ('Arduino Sensor', 499);
```

Update:

```sql
UPDATE products
SET price = 450
WHERE id = 1;
```

Delete:

```sql
DELETE FROM products
WHERE id = 1;
```

---

# 🏗️ Database Schema Through SQL

You can use SQL to perform operations that are not exposed as a dedicated dashboard button.

For example:

```sql
CREATE INDEX idx_products_name
ON products(name);
```

This is especially useful for developers who prefer direct database control.

---

# 💾 Saved Queries

SQL queries can be saved from the SQL Editor.

This is useful for frequently used queries such as:

```sql
SELECT *
FROM sensor_data
ORDER BY created_at DESC;
```

Saved queries are stored in LocalBase's metadata database and associated with the project.

---

# 🌐 REST API

Every LocalBase project exposes a REST API.

For a project:

```text
myapp
```

and table:

```text
users
```

the endpoint is:

```text
http://localhost:8000/api/project/myapp/table/users
```

This endpoint can be consumed by:

* Websites
* Mobile applications
* Python applications
* IoT devices
* Desktop applications
* JavaScript applications
* Any HTTP-capable client

---

# GET Records

```http
GET /api/project/myapp/table/users
```

Example:

```bash
curl http://localhost:8000/api/project/myapp/table/users
```

Response:

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Atharva"
    }
  ],
  "count": 1,
  "limit": 50,
  "offset": 0
}
```

---

# POST Records

Send JSON:

```http
POST /api/project/myapp/table/users
```

Body:

```json
{
  "name": "Atharva",
  "email": "atharva@example.com"
}
```

Using cURL:

```bash
curl -X POST \
  http://localhost:8000/api/project/myapp/table/users \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Atharva\",\"email\":\"atharva@example.com\"}"
```

Multiple records can also be submitted as an array.

---

# PATCH Records

Update a record using its SQLite `rowid`:

```http
PATCH /api/project/myapp/table/users/1
```

Body:

```json
{
  "name": "Updated Name"
}
```

---

# DELETE Records

```http
DELETE /api/project/myapp/table/users/1
```

---

# 🔑 API Keys

LocalBase supports API keys with two roles:

```text
public
server
```

Keys are generated with a LocalBase prefix and can be:

* Created
* Listed
* Revoked
* Deleted

The dashboard masks stored keys when displaying the key list.

---

# Authentication

Clients can send a key using:

```http
Authorization: Bearer YOUR_API_KEY
```

or:

```http
X-API-Key: YOUR_API_KEY
```

Example:

```bash
curl \
  -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8000/api/project/myapp/table/users
```

> **Security note:** Treat server/private API keys as secrets. Do not put them into publicly distributed frontend JavaScript.

---

# 📡 IoT Example

LocalBase is useful for IoT applications because devices can communicate with it through HTTP.

Imagine an ESP32 collecting:

```text
Temperature
Humidity
Distance
Device ID
Timestamp
```

Your device can send:

```http
POST /api/project/iot/table/sensor_data
```

with:

```json
{
  "device_id": "ESP32-001",
  "temperature": 28.4,
  "humidity": 71.2,
  "distance": 42
}
```

The record is stored in SQLite.

Your website can then request:

```http
GET /api/project/iot/table/sensor_data
```

This allows the same LocalBase instance to act as the backend for both the device and dashboard.

---

# 🐍 Python Example

```python
import requests

url = "http://localhost:8000/api/project/iot/table/sensor_data"

data = {
    "device_id": "ESP32-001",
    "temperature": 28.4,
    "humidity": 71.2
}

response = requests.post(url, json=data)

print(response.json())
```

Read records:

```python
import requests

url = "http://localhost:8000/api/project/iot/table/sensor_data"

response = requests.get(url)

print(response.json())
```

---

# 🌐 JavaScript Example

```javascript
const response = await fetch(
    "http://localhost:8000/api/project/iot/table/sensor_data"
);

const result = await response.json();

console.log(result.data);
```

Insert:

```javascript
await fetch(
    "http://localhost:8000/api/project/iot/table/sensor_data",
    {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            device_id: "ESP32-001",
            temperature: 28.4,
            humidity: 71.2
        })
    }
);
```

---

# 📖 API Documentation

Because LocalBase is built with FastAPI, it automatically exposes interactive API documentation.

Open:

```text
http://localhost:8000/docs
```

You can inspect and test LocalBase endpoints directly from the browser.

Alternative documentation:

```text
http://localhost:8000/redoc
```

The LocalBase dashboard also provides API information and endpoint examples.

---

# ⚡ Real-Time WebSockets

LocalBase includes a WebSocket endpoint:

```text
/ws
```

Clients can connect with an optional project:

```text
ws://localhost:8000/ws?project=myapp
```

LocalBase can broadcast database events such as:

```json
{
  "type": "insert",
  "project": "myapp",
  "table": "users",
  "record": {
    "id": 1,
    "name": "Atharva"
  }
}
```

Other supported event types include:

```text
insert
update
delete
```

This makes the architecture suitable for real-time dashboards and IoT monitoring applications.

---

# 📜 Request Logs

LocalBase records API activity.

The Logs interface can display information such as:

```text
Timestamp
HTTP method
Endpoint
Status
Response time
Project
Error
```

The internal log database keeps the most recent 5000 records.

This makes it easier to debug applications and monitor API requests.

---

# 💾 Backups

LocalBase includes SQLite database backups.

Create a backup from the dashboard or API.

Backups are stored in:

```text
localbase-data/backups/
```

Example:

```text
iot-20261007-153000.db
```

The backup system uses SQLite's backup API rather than simply copying an active database file.

You can:

* Create backups
* View backups
* Download backups
* Restore backups
* Delete backups

A restore operation also creates a snapshot of the existing database before replacement.

---

# 📥 CSV Import

You can import CSV data into an existing table.

The CSV header should correspond to database columns.

Example:

```csv
device_id,temperature,humidity
ESP32-001,28.4,71.2
ESP32-002,29.1,68.7
ESP32-003,27.9,73.5
```

LocalBase matches CSV columns against the existing table schema and inserts matching records.

---

# 📤 CSV Export

Export a table:

```text
GET /api/project/{project}/table/{table}/export.csv
```

Example:

```text
/api/project/iot/table/sensor_data/export.csv
```

The response is downloadable as CSV.

---

# 📤 JSON Export

Export table data as JSON:

```text
GET /api/project/{project}/table/{table}/export.json
```

Example:

```text
/api/project/iot/table/sensor_data/export.json
```

---

# ❤️ Health Check

LocalBase provides a health endpoint:

```text
GET /api/health
```

Example response:

```json
{
  "success": true,
  "status": "ok",
  "version": "1.0.0"
}
```

This can be used by monitoring systems or deployment scripts.

---

# ℹ️ Server Information

LocalBase also exposes:

```text
GET /api/info
```

which provides information including:

* LocalBase version
* Detected base URL
* API URL
* Data directory

The implementation also respects forwarded protocol information, making it useful behind reverse proxies.

---

# 🌍 Exposing LocalBase to the Internet

LocalBase itself does not include a tunneling service.

Instead, use a reverse proxy or tunnel such as Cloudflare Tunnel.

For example, after starting LocalBase:

```bash
python localbase.py --port 8000
```

you can expose the local service through your preferred tunnel.

Your public API could then become:

```text
https://api.example.com/api
```

and your project endpoint:

```text
https://api.example.com/api/project/iot/table/sensor_data
```

This means an IoT device outside your local network can communicate with your LocalBase instance.

> **Important:** If exposing LocalBase publicly, configure authentication, firewall rules, CORS, and your reverse proxy appropriately. Do not expose an unsecured development instance to the public internet.

---

# 🖥️ LAN Hosting

By default, LocalBase binds to:

```text
127.0.0.1
```

To allow access from other devices on your network:

```bash
python localbase.py --host 0.0.0.0 --port 8000
```

You can then access it using the host computer's LAN IP:

```text
http://192.168.x.x:8000
```

This is useful for:

* IoT development
* School science projects
* Local dashboards
* Raspberry Pi deployments
* Home servers
* Development teams

---

# ⚙️ CLI Options

Run:

```bash
python localbase.py --help
```

Available options include:

```text
--host
--port
--data
--version
--reload
```

Examples:

```bash
python localbase.py
```

```bash
python localbase.py --port 9000
```

```bash
python localbase.py --host 0.0.0.0
```

```bash
python localbase.py --host 0.0.0.0 --port 9000
```

```bash
python localbase.py --data ./my-data
```

Development auto-reload:

```bash
python localbase.py --reload
```

---

# 🌱 Environment Variables

LocalBase supports environment variables for basic configuration.

### Host

```text
LOCALBASE_HOST
```

### Port

```text
LOCALBASE_PORT
```

### Data directory

```text
LOCALBASE_DATA
```

### Secret

```text
LOCALBASE_SECRET
```

Example on Windows PowerShell:

```powershell
$env:LOCALBASE_PORT="9000"
python localbase.py
```

Linux/macOS:

```bash
LOCALBASE_PORT=9000 python localbase.py
```

---

# 📦 Building a Standalone EXE

Because the core application is contained in `localbase.py`, it can be packaged using PyInstaller.

Install PyInstaller:

```bash
pip install pyinstaller
```

Build:

```bash
pyinstaller --onefile localbase.py
```

The executable will be generated under:

```text
dist/
```

Run it:

```bash
dist/localbase.exe
```

LocalBase detects PyInstaller's frozen execution environment and can place its data directory next to the executable.

---

# 🪟 Windows

Example:

```powershell
python localbase.py
```

or after packaging:

```powershell
.\localbase.exe
```

Then open:

```text
http://127.0.0.1:8000
```

---

# 🐧 Linux

```bash
python3 localbase.py
```

Or package it:

```bash
pyinstaller --onefile localbase.py
```

Then:

```bash
./localbase
```

---

# 🍎 macOS

Install the dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run:

```bash
python3 localbase.py
```

A standalone build can also be produced with PyInstaller.

---

# 🔐 Security

LocalBase includes several safeguards such as:

* Project ID validation
* Table/column identifier validation
* SQLite identifier quoting
* Parameterized row operations
* API key verification
* Project-specific API key checking
* Backup path traversal protection
* Restricted database paths
* JSON validation
* SQL error handling
* Request logging

Project IDs are restricted to safe lowercase identifiers containing letters, numbers, `_`, and `-`.

Database identifiers are validated before being used by database operations.

However, LocalBase is currently best treated as a **self-hosted developer platform**, not a hardened multi-tenant SaaS environment.

If exposing it publicly:

* Use HTTPS
* Use strong API keys
* Avoid exposing administrative endpoints unnecessarily
* Configure CORS appropriately
* Put LocalBase behind a reverse proxy where appropriate
* Restrict network access
* Keep backups protected
* Do not expose private API keys in frontend applications

---

# ⚠️ Important API Security Note

The current LocalBase API authentication mechanism supports API keys, but authentication is not enforced globally on every management endpoint.

Therefore, do not assume that simply generating an API key automatically protects the entire LocalBase administration interface.

For public deployments, additional access control and reverse-proxy protection should be considered.

---

# 🧪 Example: Complete IoT Backend

Create a project:

```bash
python localbase.py create-project iot
```

Open the dashboard and create:

```sql
CREATE TABLE sensor_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    temperature REAL,
    humidity REAL,
    distance REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Your device can then send:

```json
{
    "device_id": "ESP32-001",
    "temperature": 29.2,
    "humidity": 72.1,
    "distance": 45.7
}
```

to:

```text
POST /api/project/iot/table/sensor_data
```

Your web dashboard can read:

```text
GET /api/project/iot/table/sensor_data
```

Your SQL Editor can analyze it:

```sql
SELECT
    device_id,
    AVG(temperature) AS average_temperature
FROM sensor_data
GROUP BY device_id;
```

And your WebSocket clients can receive real-time database events.

This makes LocalBase suitable as a lightweight backend for sensor projects, dashboards, prototypes, automation systems, and other HTTP-based applications.

---

# 🧩 API Endpoint Reference

## Projects

```text
GET    /api/projects
POST   /api/projects
PATCH  /api/projects/{project}
DELETE /api/projects/{project}
```

## Tables

```text
GET  /api/project/{project}/tables
GET  /api/project/{project}/table/{table}/schema
POST /api/project/{project}/table/{table}/create
POST /api/project/{project}/table/{table}/drop
POST /api/project/{project}/table/{table}/rename
POST /api/project/{project}/table/{table}/add_column
POST /api/project/{project}/table/{table}/drop_column
```

## Records

```text
GET    /api/project/{project}/table/{table}
POST   /api/project/{project}/table/{table}
PATCH  /api/project/{project}/table/{table}/{rowid}
DELETE /api/project/{project}/table/{table}/{rowid}
```

## SQL

```text
POST /api/project/{project}/sql
```

## API Keys

```text
GET    /api/api-keys
POST   /api/api-keys
POST   /api/api-keys/{id}/revoke
DELETE /api/api-keys/{id}
```

## Logs

```text
GET    /api/logs
DELETE /api/logs
```

## Backups

```text
GET    /api/backups
POST   /api/project/{project}/backup
POST   /api/project/{project}/restore
DELETE /api/backups/{name}
GET    /api/backups/{name}/download
```

## Import / Export

```text
GET  /api/project/{project}/table/{table}/export.csv
GET  /api/project/{project}/table/{table}/export.json
POST /api/project/{project}/table/{table}/import.csv
```

## System

```text
GET /api/health
GET /api/info
```

## Saved Queries

```text
GET    /api/project/{project}/saved-queries
POST   /api/project/{project}/saved-queries
DELETE /api/saved-queries/{id}
```

## WebSocket

```text
/ws
```

---

# 🛠️ Development

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/localbase.git
cd localbase
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run in development mode:

```bash
python localbase.py --reload
```

The application will automatically reload when the Python source changes.

---

# 📁 Recommended Repository Structure

The current architecture is intentionally minimal.

```text
localbase/
│
├── localbase.py
├── requirements.txt
├── README.md
├── LICENSE
└── tests/
```

The primary application is a single Python file containing the backend and embedded dashboard.

---

# 🧠 Design Philosophy

LocalBase follows several principles.

### Local-first

Your database belongs to you.

### Simple

A backend should not require a complicated infrastructure stack for small applications.

### Portable

The entire application can be moved to another machine.

### Developer-friendly

Use the dashboard if you want a GUI.

Use SQL if you want database-level control.

Use REST if you want to integrate an application.

### Open

The project is designed to be open-source and self-hosted.

### Multipurpose

LocalBase can be used for:

* IoT
* Websites
* APIs
* Prototypes
* School projects
* Data collection
* Dashboards
* Automation
* Small applications
* Local services
* Developer tools

---

# 🆚 LocalBase vs Hosted Backend Platforms

| Feature                   | LocalBase |
| ------------------------- | --------- |
| Self-hosted               | ✅         |
| Local database            | ✅         |
| SQLite                    | ✅         |
| Web dashboard             | ✅         |
| SQL editor                | ✅         |
| REST API                  | ✅         |
| API keys                  | ✅         |
| Backups                   | ✅         |
| CSV import/export         | ✅         |
| JSON export               | ✅         |
| WebSockets                | ✅         |
| OpenAPI docs              | ✅         |
| CLI                       | ✅         |
| Single Python application | ✅         |
| External cloud required   | ❌         |
| Account required          | ❌         |
| Node.js required          | ❌         |

LocalBase is not intended to be a drop-in replacement for every Supabase service. Its goal is to provide a lightweight, self-hosted backend foundation.

---

# 🗺️ Roadmap

Possible future development includes:

* [ ] User authentication
* [ ] Row-level security
* [ ] More granular API permissions
* [ ] PostgreSQL support
* [ ] MySQL support
* [ ] Storage buckets
* [ ] File uploads
* [ ] User management
* [ ] Organizations
* [ ] Multi-user administration
* [ ] More advanced realtime subscriptions
* [ ] Database migrations
* [ ] Visual relationship designer
* [ ] Advanced indexes UI
* [ ] More powerful query builder
* [ ] Improved production security
* [ ] Docker image
* [ ] Official prebuilt binaries
* [ ] Plugin system

The roadmap should not imply that these features are currently implemented.

---

# 🤝 Contributing

Contributions are welcome.

Typical workflow:

```bash
git clone https://github.com/YOUR_USERNAME/localbase.git
cd localbase
```

Create a branch:

```bash
git checkout -b feature/my-feature
```

Make your changes.

Test them.

Then:

```bash
git add .
git commit -m "Add my feature"
git push origin feature/my-feature
```

Open a Pull Request.

---

# 🐛 Reporting Bugs

When reporting a bug, include:

* Operating system
* Python version
* LocalBase version
* Command used
* Relevant endpoint
* Error message
* Steps to reproduce

Do not post API keys, database credentials, or private data.

---

# 📜 License

LocalBase is released under the **MIT License**.

See:

```text
LICENSE
```

for the complete license text.

---

# ⭐ Support LocalBase

If LocalBase is useful to you:

⭐ Star the repository

🐛 Report bugs

💡 Suggest features

🔧 Submit pull requests

📖 Improve documentation

📢 Share the project

---

# ❤️ LocalBase

LocalBase is built around a simple idea:

> **Your backend should be yours.**

Run it locally.

Put it on a server.

Connect an IoT device.

Build a website.

Create an API.

Experiment with databases.

Expose it through your own infrastructure.

No hosted dashboard account is required.

No external database server is required.

Just Python, SQLite, and your application.

```text
┌──────────────────────────────────────────────┐
│                  LocalBase                   │
│                                              │
│       Your self-hosted backend               │
│       Simple. Local. Yours.                  │
│                                              │
│   SQLite  •  REST  •  SQL  •  WebSockets     │
│                                              │
└──────────────────────────────────────────────┘
```

**LocalBase — Your self-hosted backend. Simple, local, and yours.**
