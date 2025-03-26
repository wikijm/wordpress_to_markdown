# WordPress Article to Markdown Downloader

## Goal

This script downloads articles from a target WordPress-based website, converts their main content to Markdown format, and saves them as individual `.md` files. It aims to preserve the content structure, title, and publication date while offering flexibility in selecting articles and handling site specifics.

## Features

*   Connects to a target WordPress site specified by URL.
*   **Flexible Sitemap Handling:**
    *   Automatically discovers and parses website sitemaps (`sitemap_index.xml`, `sitemap.xml`, `post-sitemap.xml`, `sitemap-1.xml`, etc.) to find article URLs.
    *   Allows specifying a **specific sitemap URL or relative path** using the `--sitemap-file` argument, bypassing auto-discovery.
*   Extracts article URLs and their modification dates (`lastmod`) from sitemaps.
*   **Date Filtering:** Optionally downloads only articles published on or after a specific date (`--since-date`), using sitemap modification dates for initial filtering.
*   **Pattern Filtering:** Further filters URLs to target common article permalink structures (e.g., containing `/YYYY/MM/`).
*   Fetches the HTML content of each selected article.
*   Uses `BeautifulSoup4` to parse HTML and extract:
    *   Article Title (typically from `h1.entry-title`)
    *   Publication Date (from `<time class="entry-date">` or URL structure)
    *   Main Content (typically from `div.entry-content`)
*   Uses `html2text` to convert the extracted HTML content to Markdown, preserving original external image/resource URLs.
*   Adds metadata (`**Date:**`, `**Source URL:**`) to the top of each Markdown file.
*   Saves each article as a separate `.md` file named `YYYY-MM-DD-article-title.md` (using the date extracted from the article page).
*   Includes basic "anti-bot" measures:
    *   Uses a rotating list of realistic browser User-Agent strings.
    *   Sends common browser headers.
    *   Uses a `requests.Session` for connection persistence and cookie handling.
    *   Introduces randomized delays between requests.
*   Performs an initial connectivity check to `wp.com`.
*   Allows disabling SSL certificate verification (`--disable-ssl`) for sites with problematic certificates (use with caution).
*   Provides command-line arguments for configuration.

## Prerequisites

*   **Python 3:** Version 3.7 or higher is recommended.
*   **pip:** The Python package installer (usually included with Python).

## Setup

1.  **Save the Script:** Save the Python code provided previously as a file named `wordpress_to_markdown.py` (or your preferred name).
2.  **Install Dependencies:** Open your terminal or command prompt, navigate to the directory where you saved the script, and install the required Python libraries:
    ```bash
    pip install requests beautifulsoup4 html2text lxml
    ```
    *(lxml is used by BeautifulSoup for potentially faster/more robust HTML/XML parsing)*
3.  **(Optional) Make Executable:** On Linux/macOS, you can make the script directly executable:
    ```bash
    chmod +x wordpress_to_markdown.py
    ```

## Usage

Run the script from your terminal using the `python` interpreter (or directly if made executable). You must provide either a base URL (`--url`) for auto-discovery or a specific sitemap file (`--sitemap-file`).

```bash
python wordpress_to_markdown.py [ARGUMENTS]
```

Or, if executable:

```bash
./wordpress_to_markdown.py [ARGUMENTS]
```

### Command-Line Arguments

*   `--url URL`: (Optional, but required if `--sitemap-file` is relative or not provided) The base URL of the WordPress site (e.g., `https://wordpresswebsite.tld`). Used for sitemap auto-discovery and constructing absolute URLs.
*   `--sitemap-file SITEMAP_PATH_OR_URL`: (Optional) Explicitly provide the URL or relative path (e.g., `sitemap-1.xml`) of the sitemap file (index or URL list) to use.
    *   If a full URL is given, it's used directly. `--url` is only needed if you want to override the inferred base domain for filtering.
    *   If a relative path (like `sitemap.xml` or `/sitemaps/posts.xml`) is given, `--url` **must** also be provided to construct the full sitemap URL.
    *   Using this bypasses the auto-discovery process.
*   `--disable-ssl`: (Optional) Add this flag to disable SSL certificate verification. Useful for sites with self-signed or invalid certificates, but **use with caution** as it reduces security.
*   `--since-date YYYY-MM-DD`: (Optional) Only download articles where the sitemap's `lastmod` date is on or after this date. The date **must** be in `YYYY-MM-DD` format (e.g., `2024-01-01`). Articles without a valid date in the sitemap might be excluded when this filter is active (check script output).

### Examples

1.  **Auto-discover sitemap and download all articles from `wordpresswebsite.tld` (disabling SSL):**
    ```bash
    python wordpress_to_markdown.py --url https://wordpresswebsite.tld --disable-ssl
    ```

2.  **Auto-discover and download articles since January 1st, 2024 from `wordpresswebsite.tld` (disabling SSL):**
    ```bash
    python wordpress_to_markdown.py --url https://wordpresswebsite.tld --disable-ssl --since-date 2024-01-01
    ```

3.  **Use a specific sitemap file (`sitemap-1.xml`) from `wordpresswebsite.tld` (disabling SSL):**
    *   *Option 1: Relative path (requires `--url`)*
        ```bash
        python wordpress_to_markdown.py --url https://wordpresswebsite.tld --sitemap-file sitemap-1.xml --disable-ssl
        ```
    *   *Option 2: Full URL*
        ```bash
        python wordpress_to_markdown.py --sitemap-file https://wordpresswebsite.tld/sitemap-1.xml --disable-ssl
        ```

4.  **Download all articles from a different site using auto-discovery (assuming valid SSL):**
    ```bash
    python wordpress_to_markdown.py --url https://example-wordpress-blog.com
    ```

### Output

The script will create a directory named `markdown_articles` (in the same location where you run the script) and save the downloaded `.md` files inside it. Each file will be named using the format `YYYY-MM-DD-article-title.md`.

## How It Works (High-Level)

1.  Parses command-line arguments.
2.  Determines the target domain and the specific sitemap URL to use (either via `--sitemap-file` or auto-discovery triggered by `--url`).
3.  Performs a quick connectivity check.
4.  Creates a `requests` session with randomized headers.
5.  Fetches and parses the entry sitemap (which might be an index file). If it's an index, fetches and parses the sub-sitemaps listed.
6.  Extracts all article URLs and modification dates (`lastmod`) from the sitemap(s). Removes duplicates.
7.  Filters URLs based on the `--since-date` (if provided), using the `lastmod` dates.
8.  Further filters URLs to include only those matching the target domain and common article path patterns (e.g., containing `/YYYY/MM/`).
9.  For each remaining URL:
    *   Fetches the article's HTML page.
    *   Parses the HTML to find the title, publication date (from the page), and main content area.
    *   Converts the main content HTML to Markdown.
    *   Saves the result as `YYYY-MM-DD-title.md` with metadata headers.
    *   Waits for a random delay before processing the next article.

## Important Notes

*   **SSL Verification:** Disabling SSL verification (`--disable-ssl`) bypasses security checks. Only use it if necessary and you understand the risks.
*   **Bot Detection:** Basic anti-bot measures are included, but they won't defeat advanced systems. **Use responsibly.**
*   **Website Structure Dependency:** The script relies on common WordPress HTML/sitemap structures (e.g., `h1.entry-title`, `div.entry-content`, `<time class="entry-date">`). It may fail or produce incomplete results on heavily customized sites.
*   **Date Filtering Reliability:** Filtering using `--since-date` depends on the accuracy and presence of the `<lastmod>` tag in the website's sitemap XML. If dates are missing or incorrect there, the filtering may be inaccurate.
*   **Rate Limiting & Terms of Service:** Respect the target website's `robots.txt` and Terms of Service. The randomized delay helps, but avoid excessive use. Adjust `MIN_DELAY` and `MAX_DELAY` in the script if needed for politeness.

## License

Consider adding an open-source license (e.g., MIT License) if you plan to share this script.
