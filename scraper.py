import os
import argparse
import pandas as pd
from urllib.parse import urlparse
from pathlib import Path
from tqdm import tqdm
from playwright.sync_api import sync_playwright
from PIL import Image
import numpy as np
import shutil

def white_ratio(im_path, threshold=230):
  img = Image.open(im_path).convert('RGB')
  arr = np.array(img)

  return np.mean(((arr[:, :, 0] > threshold) & (arr[:, :, 1] > threshold) & (arr[:, :, 2] > threshold)))

def is_url(s):
  return s.startswith('http://') or s.startswith('https://')

def download_image(context, img_url, save_path):
  response = context.request.get(img_url)
  if response.ok:
    with open(save_path, 'wb') as f:
      f.write(response.body())
    return True
  return False

def extract_links(page, url):
  page.goto(url)

  while True:
    try:
      btn = page.locator('//button[@data-auto="btnPLPShowMore"]')
      if btn.is_visible():
        btn.scroll_into_view_if_needed()
        btn.click()
        page.wait_for_timeout(800)
      else:
        break
    except:
      break

  return pd.Series(['https://us.pandora.net' + link.get_attribute("href").split("?")[0] for link in page.locator('//a[@data-testid="product-tile"]').all() if link.get_attribute("href")])

def extract_product(page, context, url, direct_download):
  path = urlparse(url).path
  parts = path.strip('/').split('/')

  if len(parts) < 3 or not parts[-1].endswith('.html'):
    return None

  category = parts[1]
  product_id = parts[-1].removesuffix(".html")

  os.makedirs(f'data/images/{product_id}', exist_ok=True)

  white_r = []

  if not direct_download:
    saved = []
    
    def handle_response(response):
      if response.status == 200 and '/dw/image/' in response.url and product_id in response.url:
        try:
          saved.append(response.body())
        except:
          pass

    page.on('response', handle_response)

  page.goto(url, wait_until='domcontentloaded')
  page.wait_for_selector('//span[@data-auto="lblRegularPrice"]', timeout=15000)

  if not direct_download:
    page.remove_listener('response', handle_response)

    for i, img_bytes in enumerate(saved):
      with open(f'data/images/{product_id}/{i}.png', 'wb') as f:
        f.write(img_bytes)
        white_r.append(white_ratio(f'data/images/{product_id}/{i}.png'))

  name = page.locator('//h1[@data-auto="productName"]').text_content().strip()

  try:
    price = page.locator('//span[@data-auto="lblRegularPrice"]').text_content().strip()
  except:
    try:
      price = page.locator('//p[@data-auto="addToBagDefaultProductPrice"]').text_content().strip()
    except:
      price = None
  
  if direct_download:
    img_urls = [s.split('?')[0] + '?sfrm=png' for s in page.eval_on_selector_all('//img[@itemprop="image"]', 'imgs => imgs.map(img => img.src)') if s]

    for i, img_url in enumerate(img_urls):
      download_image(context, img_url, f'data/images/{product_id}/{i}.png')
      white_r.append(white_ratio(f'data/images/{product_id}/{i}.png'))

  shutil.copy2(f'data/images/{product_id}/{max(range(len(white_r)), key=lambda i: white_r[i])}.png', f'data/images/{product_id}/main.png')

  details_btn = page.locator('//*[@data-auto="moreLinkDetails"]')
  if details_btn.is_visible():
    details_btn.click()
    page.wait_for_timeout(300)

  desc = None
  desc_el = page.locator('//div[@data-auto="productDescription"]')
  if desc_el.count() > 0:
    p = desc_el.locator("p")
    if p.count() > 0:
      desc = p.first.text_content().strip()

  materials = [m.text_content().strip() for m in page.locator('//h2[@data-auto="materialDetailStyle"]').all()] or None

  dimensions = None
  dim_el = page.locator('//p[@data-auto="dimensions"]/following-sibling::p[1]')

  if dim_el.first.is_visible():
    dimensions = dim_el.first.inner_text().strip()

  return {
    'id': product_id,
    'category': category,
    'url': url,
    'name': name,
    'description': desc,
    'price': price,
    'dimensions': dimensions,
    'materials': materials
  }

def entry():
  parser = argparse.ArgumentParser()
  parser.add_argument('url')
  parser.add_argument('--direct_download', action='store_true')
  args = parser.parse_args()
  os.makedirs('data/images', exist_ok=True)

  p = sync_playwright().start()
  browser = p.chromium.launch(headless=False)
  context = browser.new_context(viewport={'width': 1920, 'height': 1080})
  page = context.new_page()
  
  if is_url(args.url):
    print('Extracting links...')

    parsed = urlparse(args.url)
    parts = [p for p in parsed.path.split('/') if p]

    if len(parts) < 2 or parts[0] != 'en':
      raise ValueError('Unexpected URL format')

    identifier = parts[1]

    links = extract_links(page, args.url)
    links.to_csv(f'data/{identifier}-links.csv', index=False, header=False)
  else:
    print('Using existing link list')
    path = Path(args.url)
    if not path.exists():
      raise FileNotFoundError(f'{args.url} not found')

    identifier = path.stem.split('-')[0]
    links = pd.read_csv(path, header=None).squeeze('columns')

  identifier += '^'
  
  print(f'Extracted {len(links)} product links')

  start_index = 0
  output_file = Path(f'data/{identifier}.csv')
  if output_file.exists():
    existing = pd.read_csv(output_file)

    if not existing.empty:
      last_id = existing.iloc[-1]['id']

      for i, link in enumerate(links):
        if last_id in link:
          start_index = i + 1
          break

      print(f'Resuming from index {start_index}')

  success = 0

  links = links[start_index:]

  pbar = tqdm(links, desc='Products')
  for link in pbar:
    try:
      row = extract_product(page, context, link, args.direct_download)

      if row:
        pd.DataFrame([row]).to_csv(output_file, mode='a', header=not output_file.exists(), index=False)
        success += 1

      if success % 20 == 0:
        context.close()
        browser.close()
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

      pbar.set_postfix({'success': success, 'rate': f'{(success-1) / pbar.n:.2%}' if pbar.n else '0%'})
    except Exception as e:
      print(f'Error on {link}: {e}')
      

  print(f'Successfully scarped {success} out of {len(links)} ({(success/len(links)*100):.2f}%)')

  context.close()
  browser.close()
  p.stop()

if __name__ == '__main__':
  entry()