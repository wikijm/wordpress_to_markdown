#!/usr/bin/env python3

import requests
import sys
import re
import os
import time
import random
import argparse
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import html2text
from datetime import datetime, date

# --- Default Configuration (can be overridden by args) ---
OUTPUT_DIR = "markdown_articles"
USER_AGENT_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0'
]
MIN_DELAY = 2.0
MAX_DELAY = 5.0
CONNECTIVITY_CHECK_URL = "https://wp.com"
SITEMAP_SUFFIXES = [
    "/sitemap_index.xml", "/sitemap.xml", "/post-sitemap.xml",
    "/sitemap-pt-post-1.xml", "/sitemap-1.xml",
]
# --- End Configuration ---

# --- Standard Browser Headers ---
BASE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9', 'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive', 'Upgrade-Insecure-Requests': '1',
}

# --- Helper Functions ---

def check_connectivity(url_to_check, disable_ssl_verify):
    """Checks if a given URL is reachable."""
    print(f"[*] Checking connectivity to {url_to_check}...")
    verify_ssl = not disable_ssl_verify
    try:
        response = requests.head(url_to_check, timeout=15, verify=verify_ssl)
        response.raise_for_status()
        print(f"[+] Connectivity check successful ({response.status_code}).")
        return True
    except requests.exceptions.SSLError as e:
         print(f"[!] SSL Error during connectivity check: {e}", file=sys.stderr)
         if not verify_ssl: pass
         else: print("[!] Consider using --disable-ssl if this is expected.")
         return False
    except requests.exceptions.RequestException as e:
        print(f"[!] Connectivity check failed: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[!] Unexpected error during connectivity check: {e}", file=sys.stderr)
        return False

def create_session(disable_ssl_verify):
    """Creates a requests Session object."""
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    chosen_user_agent = random.choice(USER_AGENT_LIST)
    session.headers.update({'User-Agent': chosen_user_agent})
    print(f"[*] Session created with User-Agent: {chosen_user_agent}")
    session.verify = not disable_ssl_verify
    if not session.verify:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return session

def fetch_url(session, url, is_xml=False):
    """Fetches content using the provided session."""
    print(f"[*] Fetching: {url}")
    if url.startswith("data:"): return None
    try:
        response = session.get(url, timeout=45)
        response.raise_for_status()
        if is_xml:
            content_type = response.headers.get('Content-Type', '').lower()
            if 'xml' not in content_type:
                print(f"[!] Warning: Expected XML, got {content_type}", file=sys.stderr)
            return response.content
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"[!] Request Error fetching {url}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[!] Unexpected error fetching {url}: {e}", file=sys.stderr)
        return None

def parse_sitemap_index(xml_content):
    """Parses an XML sitemap index file."""
    sitemap_urls = []
    if not xml_content: return sitemap_urls
    print("[*] Parsing sitemap index XML...")
    try:
        root = ET.fromstring(xml_content)
        ns_uri = root.tag.split('}')[0][1:] if '}' in root.tag else 'http://www.sitemaps.org/schemas/sitemap/0.9'
        ns = {'ns': ns_uri}
        for sm in root.findall('ns:sitemap', ns):
            loc = sm.find('ns:loc', ns)
            if loc is not None and loc.text: sitemap_urls.append(loc.text.strip())
        print(f"[*] Found {len(sitemap_urls)} URLs in sitemap index.")
    except Exception as e: print(f"[!] Error parsing sitemap index: {e}", file=sys.stderr)
    return sitemap_urls

def parse_url_sitemap(xml_content):
    """Parses a URL sitemap file."""
    url_data = []
    if not xml_content: return None # Indicate failure clearly if no content
    print("[*] Parsing URL sitemap XML...")
    try:
        root = ET.fromstring(xml_content)
        namespace_uri = ''
        if '}' in root.tag: namespace_uri = root.tag.split('}')[0][1:]
        if not namespace_uri: namespace_uri = 'http://www.sitemaps.org/schemas/sitemap/0.9'
        namespace = {'ns': namespace_uri}

        for url_element in root.findall('ns:url', namespace):
            loc_element = url_element.find('ns:loc', namespace)
            lastmod_element = url_element.find('ns:lastmod', namespace)
            url = loc_element.text.strip() if loc_element is not None and loc_element.text else None
            lastmod = lastmod_element.text.strip() if lastmod_element is not None and lastmod_element.text else None
            if url: url_data.append((url, lastmod))

        print(f"[*] Found {len(url_data)} URLs in sitemap.")
    except ET.ParseError as e:
        print(f"[!] XML Parse Error in URL sitemap: {e}", file=sys.stderr)
        if xml_content:
            snippet = xml_content[:500].decode('utf-8', errors='ignore') if isinstance(xml_content, bytes) else xml_content[:500]
            print(f"    Nearby content: {snippet}...", file=sys.stderr)
        return None # Indicate failure clearly
    except Exception as e:
        print(f"[!] Unexpected Error parsing URL sitemap: {e}", file=sys.stderr)
        return None # Indicate failure clearly
    return url_data

def filter_articles_by_date(url_data, since_date_str, exclude_no_date=True):
    """
    Filters the list of (URL, lastmod) tuples based on the since_date.
    By default, excludes articles without a valid parseable date when filtering.
    """
    if not since_date_str:
        print("[*] No --since-date provided, skipping date filtering.")
        return url_data

    print(f"[*] Filtering articles published on or after {since_date_str}...")
    filtered_data = []
    try:
        since_dt = datetime.strptime(since_date_str, '%Y-%m-%d').date()
    except ValueError:
        print(f"[!] Invalid --since-date format '{since_date_str}'. Skipping date filtering.", file=sys.stderr)
        return url_data

    kept_count = 0
    skipped_by_date_count = 0
    skipped_no_date_count = 0
    error_count = 0

    print(f"    Filtering {len(url_data)} total URLs...")

    for url, lastmod_str in url_data:
        if not lastmod_str:
            if exclude_no_date:
                # print(f"    [Filter Debug] Skipping (no lastmod date): {url}") # Verbose
                skipped_no_date_count += 1
            else:
                # print(f"    [Filter Debug] Keeping (no lastmod date, exclude_no_date=False): {url}") # Verbose
                filtered_data.append((url, None))
                kept_count += 1
            continue

        try:
            article_dt = datetime.fromisoformat(lastmod_str.replace('Z', '+00:00')).date()
            comparison = article_dt >= since_dt
            # print(f"    [Filter Debug] Compare: {url} | {article_dt} >= {since_dt} ? {comparison}") # Verbose
            if comparison:
                filtered_data.append((url, lastmod_str))
                kept_count += 1
            else:
                skipped_by_date_count +=1
        except ValueError:
            error_count += 1
            print(f"    [Filter Debug] Skipping (ValueError parsing lastmod '{lastmod_str}'): {url}")
        except Exception as e:
            error_count += 1
            print(f"    [Filter Debug] Skipping (Error parsing lastmod '{lastmod_str}' - {e}): {url}")

    print(f"[*] Date Filtering Results: Kept={kept_count}, Skipped(Date)={skipped_by_date_count}, Skipped(NoDate/Error)={skipped_no_date_count + error_count}")
    return filtered_data

def parse_and_convert_article(html_content, base_url):
    """Parses article HTML, extracts metadata, converts to Markdown."""
    if not html_content: return None, None, None
    soup = BeautifulSoup(html_content, 'html.parser')
    title, date_str, markdown = "Untitled Article", None, None
    title_tag = soup.find('h1', class_='entry-title')
    if title_tag: title = title_tag.get_text(strip=True)
    else: print(f"[!] Warn: No title for {base_url}")
    time_tag = soup.find('time', class_='entry-date')
    if time_tag and time_tag.has_attr('datetime'):
        dt_attr = time_tag['datetime']
        try: date_str = datetime.fromisoformat(dt_attr.replace('Z', '+00:00')).strftime('%Y-%m-%d'); print(f"[*] Article Date: {date_str}")
        except Exception as e: print(f"[!] Warn: Bad date attr '{dt_attr}': {e}")
    else:
        match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', base_url)
        if match: date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"; print(f"[*] Article Date (URL): {date_str}")
        else: print(f"[!] Warn: No date for {base_url}")
    content_div = soup.find('div', class_='entry-content')
    if not content_div: print(f"[!] No content for {base_url}", file=sys.stderr); return title, date_str, None
    print("[*] Converting to Markdown...")
    h = html2text.HTML2Text(); h.ignore_links,h.ignore_images,h.body_width,h.unicode_snob,h.bypass_tables,h.baseurl = False,False,0,True,False,base_url
    try: markdown = h.handle(str(content_div))
    except Exception as e: print(f"[!] Convert error: {e}", file=sys.stderr); return title, date_str, None
    return title, date_str, markdown

def clean_filename(title, date_str):
    """Cleans title, prepends date for filename."""
    cl_title = re.sub(r'[^\w\-\s]', '', title); cl_title = re.sub(r'\s+', '-', cl_title).strip('-'); cl_title = re.sub(r'-+', '-', cl_title).lower()
    max_len = 180
    if len(cl_title) > max_len:
        try: cl_title = cl_title[:max_len].rsplit('-', 1)[0]
        except IndexError: cl_title = cl_title[:max_len]
    if not cl_title: cl_title = "unnamed-article"
    if date_str and re.match(r'\d{4}-\d{2}-\d{2}', date_str): return f"{date_str}-{cl_title}.md"
    else:
        if date_str: print(f"[!] Warn: Bad date '{date_str}', not prepending.")
        return f"{cl_title}.md"

def save_markdown(filename, title, date_str, markdown_content, source_url):
    """Saves Markdown content to file."""
    try: os.makedirs(OUTPUT_DIR, exist_ok=True)
    except OSError as e: print(f"[!] Cannot create dir {OUTPUT_DIR}: {e}", file=sys.stderr); return False
    filepath = os.path.join(OUTPUT_DIR, filename); print(f"[*] Saving to: {filepath}")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"**Date:** {date_str or 'N/A'}\n\n"); f.write(f"**Source URL:** <{source_url}>\n\n"); f.write(f"# {title}\n\n"); f.write(markdown_content)
        print(f"[+] Saved: {filepath}"); return True
    except Exception as e: print(f"[!] Save error: {e}", file=sys.stderr); return False

def random_delay():
    """Pauses execution randomly."""
    delay = random.uniform(MIN_DELAY, MAX_DELAY); print(f"[*] Waiting {delay:.2f}s..."); time.sleep(delay)

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description="Download WordPress articles as Markdown.")
    parser.add_argument("--url", help="Base URL of the target site (e.g., https://thedfirreport.com). Required if --sitemap-file is relative or not provided.")
    parser.add_argument("--disable-ssl", action="store_true", help="Disable SSL certificate verification.")
    parser.add_argument("--since-date", help="Only download articles on or after this date (YYYY-MM-DD).")
    parser.add_argument("--sitemap-file", help="URL or relative path (e.g., 'sitemap.xml') of the sitemap file. If relative, --url must be provided.")

    args = parser.parse_args()

    base_url, target_domain, final_sitemap_url = None, None, None

    if args.url:
        parsed_target_url = urlparse(args.url)
        if not parsed_target_url.scheme or not parsed_target_url.netloc: sys.exit(f"[!] Invalid --url: {args.url}.")
        base_url = f"{parsed_target_url.scheme}://{parsed_target_url.netloc}"; target_domain = parsed_target_url.netloc

    if args.sitemap_file:
        sitemap_arg = args.sitemap_file; parsed_sitemap_arg = urlparse(sitemap_arg)
        if parsed_sitemap_arg.scheme and parsed_sitemap_arg.netloc:
            final_sitemap_url = sitemap_arg
            if not base_url: base_url = f"{parsed_sitemap_arg.scheme}://{parsed_sitemap_arg.netloc}"; target_domain = parsed_sitemap_arg.netloc; print(f"[*] Inferred Base URL: {base_url}")
        elif base_url: final_sitemap_url = urljoin(base_url, sitemap_arg.lstrip('/')); print(f"[*] Combined URL: {final_sitemap_url}")
        else: sys.exit("[!] Error: --sitemap-file is relative, but --url not provided.")
    elif not base_url: sys.exit("[!] Error: Must provide --url or --sitemap-file.")
    if not target_domain: sys.exit("[!] Critical Error: Could not determine target domain.")

    if args.since_date:
        try: datetime.strptime(args.since_date, '%Y-%m-%d')
        except ValueError: sys.exit(f"[!] Error: Invalid --since-date format: '{args.since_date}'.")

    start_time = time.time()
    print(f"--- Starting Article Batch Download ---")
    print(f"[*] Target Domain: {target_domain}")
    if final_sitemap_url: print(f"[*] Sitemap URL: {final_sitemap_url}")
    else: print(f"[*] Using Auto-Discovery from: {base_url}")
    print(f"[*] Output Directory: {OUTPUT_DIR}")
    print(f"[*] Delay: {MIN_DELAY:.1f}s - {MAX_DELAY:.1f}s")
    if args.since_date: print(f"[*] Filtering since: {args.since_date}")
    if args.disable_ssl: print("[!] SSL Verification: DISABLED")

    if not check_connectivity(CONNECTIVITY_CHECK_URL, args.disable_ssl): sys.exit("[!] Connectivity check failed.")

    session = create_session(args.disable_ssl)

    all_url_data = []
    sitemaps_to_process = []
    sitemap_found = False

    if final_sitemap_url:
        print(f"[*] Using explicit sitemap URL: {final_sitemap_url}")
        xml_content = fetch_url(session, final_sitemap_url, is_xml=True)
        if xml_content:
            temp_sitemap_urls = parse_sitemap_index(xml_content)
            if temp_sitemap_urls:
                 print(f"[*] Index sitemap found. Adding sub-sitemaps."); sitemaps_to_process.extend(temp_sitemap_urls); sitemap_found = True
            else:
                 url_data_check = parse_url_sitemap(xml_content)
                 if url_data_check is not None: print(f"[*] URL sitemap found."); sitemaps_to_process.append(final_sitemap_url); sitemap_found = True
                 else: print(f"[!] Failed parse: {final_sitemap_url}")
        else: print(f"[!] Failed fetch: {final_sitemap_url}")
    else:
        print(f"[*] Auto-discovering sitemap from: {base_url}")
        for suffix in SITEMAP_SUFFIXES:
            sitemap_url = urljoin(base_url, suffix.lstrip('/')); print(f"[*] Attempting: {sitemap_url}")
            xml_content = fetch_url(session, sitemap_url, is_xml=True)
            if xml_content:
                temp_sitemap_urls = parse_sitemap_index(xml_content)
                if temp_sitemap_urls: print(f"[*] Index found."); sitemaps_to_process.extend(temp_sitemap_urls); sitemap_found = True; break
                else:
                    url_data_check = parse_url_sitemap(xml_content)
                    if url_data_check is not None: print(f"[*] URL sitemap found."); sitemaps_to_process.append(sitemap_url); sitemap_found = True
                    else: print(f"[*] Found, but failed parse.")
            else: print(f"[*] Not found/fetch failed."); random_delay()
        if not sitemap_found and sitemaps_to_process: print("[*] No index, using discovered URL sitemaps."); sitemap_found = True

    if not sitemap_found or not sitemaps_to_process: sys.exit(f"[!] No valid sitemaps found/processed.")

    print(f"\n[*] Processing {len(sitemaps_to_process)} sitemap file(s)...")
    for sitemap_url in sitemaps_to_process:
        print(f"--- Processing sitemap: {sitemap_url} ---")
        xml_content = fetch_url(session, sitemap_url, is_xml=True)
        if xml_content:
            url_data = parse_url_sitemap(xml_content)
            if url_data is not None: all_url_data.extend(url_data)
            else: print(f"[!] Skipping results from failed parse: {sitemap_url}")
            random_delay()
        else: print(f"[!] Failed fetch/parse: {sitemap_url}"); random_delay()

    if not all_url_data: sys.exit("[!] No URLs found in sitemaps.")

    unique_url_data_dict = {url: lastmod for url, lastmod in all_url_data}
    unique_url_data = list(unique_url_data_dict.items())
    print(f"\n[*] Found {len(unique_url_data)} unique URLs.")

    filtered_url_data = filter_articles_by_date(unique_url_data, args.since_date)
    print(f"[*] After date filtering: {len(filtered_url_data)} URLs remain.")

    url_pattern_regex = re.compile(r"/\d{4}/\d{2}(?:/\d{2})?/")
    final_urls_to_process = []
    print(f"\n[*] Filtering for domain '{target_domain}' & article pattern...")
    skipped_pattern_count = 0
    for url, _ in filtered_url_data:
        parsed_url = urlparse(url)
        if parsed_url.netloc == target_domain and url_pattern_regex.search(parsed_url.path): final_urls_to_process.append(url)
        else: skipped_pattern_count += 1
    print(f"[*] Domain/Pattern Filter: Kept={len(final_urls_to_process)}, Skipped={skipped_pattern_count}")

    if not final_urls_to_process: sys.exit("[!] No URLs matched all criteria.")

    print(f"\n--- Processing {len(final_urls_to_process)} final articles ---")
    success_count, fail_count = 0, 0
    for i, article_url in enumerate(final_urls_to_process):
        print("-" * 10); print(f"[*] Processing {i+1}/{len(final_urls_to_process)}: {article_url}")
        html_content = fetch_url(session, article_url)
        if not html_content: fail_count += 1; random_delay(); continue
        title, article_date_str, md_content = parse_and_convert_article(html_content, article_url)
        if not md_content: print(f"[!] Failed convert: {article_url}", file=sys.stderr); fail_count += 1; random_delay(); continue
        filename = clean_filename(title, article_date_str)
        if save_markdown(filename, title, article_date_str, md_content, article_url): success_count += 1
        else: fail_count += 1
        random_delay()

    end_time = time.time()
    print("\n" + "=" * 30)
    print("--- Batch Processing Complete ---")
    print(f"Success: {success_count}, Fail/Skip: {fail_count}, Total: {len(final_urls_to_process)}")
    print(f"Output: {os.path.abspath(OUTPUT_DIR)}")
    print(f"Time: {end_time - start_time:.2f}s")
    print("=" * 30)

if __name__ == "__main__":
    main()
