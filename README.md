# News Trader

## Project Goal

This project aims to build a Django-based backend system that automates financial trading based on insights derived from social media posts. It scrapes posts from configurable sources, uses a Large Language Model (LLM) to assess potential financial impact, and executes trades via the Alpaca API. The system also provides a real-time dashboard for monitoring and allows manual intervention for closing positions.

## Tech Stack

*   **Backend:** Python 3.11+, Django 4.x
*   **Database:** PostgreSQL
*   **Task Queue:** Celery + Redis
*   **LLM Access:** OpenAI API (or compatible local server)
*   **Trading:** Alpaca API
*   **Containerization:** Docker, Docker Compose

## Core Modules

*   **Web Scraper:** A Celery task that performs traditional web scraping from configurable URLs.
*   **API Fetcher:** A Celery task that fetches data from configurable API endpoints.
*   **Analysis Agent:** Sends new posts to an LLM for financial impact assessment and saves the analysis results.
*   **Trader Service:** Places orders via Alpaca based on LLM insights and monitors open positions.
*   **Admin + Real-Time Dashboard:** For configuration, monitoring, and manual trade management.
*   **Post-Trade Linking:** Links every trade back to the triggering post and analysis for auditing and future LLM fine-tuning.

## Setup and Running the Project

### Prerequisites

*   Docker and Docker Compose installed.
*   Python 3.11+ (for local development, though Docker handles the environment).

### 1. Environment Variables

Create a `.env` file in the project root directory with your API keys:

```
ALPACA_API_KEY=YOUR_ALPACA_API_KEY
ALPACA_SECRET_KEY=YOUR_ALPACA_SECRET_KEY
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
NEWSAPI_API_KEY=YOUR_ACTUAL_NEWSAPI_KEY # Example for NewsAPI
```

Replace `YOUR_ALPACA_API_KEY`, `YOUR_ALPACA_SECRET_KEY`, `YOUR_OPENAI_API_KEY`, and `YOUR_ACTUAL_NEWSAPI_KEY` with your actual credentials.

### 2. Build and Run Docker Containers

Navigate to the project root directory in your terminal and run:

```bash
docker-compose up -d --build
```

This command will:

*   Build the Docker images for the `web`, `celery`, and `celery-beat` services.
*   Start the PostgreSQL database (`db`), Redis server (`redis`), Django web application (`web`), Celery worker (`celery`), and Celery beat scheduler (`celery-beat`) in detached mode.

### 3. Apply Database Migrations

Once the containers are running, apply the Django database migrations:

```bash
docker-compose exec web python manage.py migrate
```

### 4. Create Superuser

Create a Django superuser to access the admin interface:

```bash
docker-compose exec web python manage.py createsuperuser --noinput --username admin --email admin@example.com
docker-compose exec web python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); u = User.objects.get(username='admin'); u.set_password('admin'); u.save()"
```

This creates a superuser with username `admin` and password `admin`.

### 5. Access the Application

*   **Django Admin:** Open your web browser and go to `http://localhost:8000/admin/`. Log in with the superuser credentials (`admin`/`admin`).
*   **Dashboard:** `http://localhost:8000/dashboard/`
*   **Test Page:** `http://localhost:8000/test-page/`

### 6. Stopping the Project

To stop all running Docker containers, run:

```bash
docker-compose down
```

To stop and remove all containers, networks, and volumes (including database data), run:

```bash
docker-compose down -v
```

## Configuring Sources

Sources can be configured in the Django Admin (`http://localhost:8000/admin/core/source/`). Each source defines how posts are obtained.

### Web Scraping Source Configuration

For traditional web scraping, configure a `Source` with:

*   **Name:** A descriptive name (e.g., `My Blog News`).
*   **URL:** The URL of the website to scrape (e.g., `https://www.example.com/blog`).
*   **Description:** (Optional) Notes about this source.
*   **Scraping method:** Select `Web Scraping`.
*   **Request Type:** `GET` (typically for web scraping).
*   **Request Parameters:** (Optional) JSON for any specific query parameters if the URL itself doesn't contain them.

### API Fetching Source Configuration (e.g., NewsAPI)

To fetch posts from an API, configure a `Source` with:

*   **Name:** A descriptive name for your API source (e.g., `NewsAPI - Tesla News`).
*   **URL:** This field is still required but can be a base URL or a placeholder for API sources (e.g., `https://newsapi.org/`).
*   **Description:** (Optional) Add any relevant notes about this API source.
*   **Scraping method:** Select `API`.
*   **Request Type:** Select `GET` or `POST` depending on the API's requirements.
*   **API Endpoint:** The full API endpoint URL (e.g., `https://newsapi.org/v2/everything`).
*   **API Key Field:** The name of the environment variable (from your `.env` file) that holds the API key (e.g., `NEWSAPI_API_KEY`). **Do NOT put your actual API key here.**
*   **Request Parameters:** A JSON object representing the parameters for your API request. This can include query parameters for GET requests or body data for POST requests. For example, for NewsAPI's `/v2/everything` endpoint, you might use:

    ```json
    {
        "q": "tesla",
        "from": "2025-07-01",
        "sortBy": "publishedAt"
    }
    ```

    **Important:** The `apiKey` parameter should NOT be included in `request_params` if you are using `api_key_field`. The system will automatically add the API key from the specified environment variable as an `Authorization: Bearer` header.

## Known Issues

*   **Direct Web Scraping of Dynamic Sites:** Direct web scraping of sites like `https://truthsocial.com/` often results in a `403 Forbidden` error due to anti-bot measures. For testing purposes, the `scrape_posts` task is configured to create a simulated post if a real web scraping attempt fails. This allows the downstream LLM analysis and trading components to be tested.

## Next Steps / Development

*   Refine LLM prompt and integrate more sophisticated analysis.
*   Implement real-time dashboard using Django Channels or similar.
*   Develop UI for manual trade closing.
*   Add comprehensive error handling and logging.
*   Implement unit and integration tests.