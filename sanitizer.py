import os
import argparse
import glob
import shutil
import pandas as pd

def entry():
  parser = argparse.ArgumentParser()
  parser.add_argument('--files', nargs='+', type=str, help='list of csv directories')
  parser.add_argument('--no_sanitize', action='store_true')
  parser.add_argument('--out', type=str, default='data/merged.csv')
  args = parser.parse_args()

  if args.files:
    csv_files = args.files
  else:
    csv_files = [f for f in glob.glob('data/*.csv') if '^' in os.path.basename(f)]

  if not csv_files:
    print('no csv files')
    return
  
  print('merging files...')
  dfs = [pd.read_csv(f) for f in csv_files]
  merged = pd.concat(dfs, ignore_index=True).drop_duplicates(subset="id")

  valid_ids = []
  invalid = 0

  for product_id in merged['id']:
    image_dir = os.path.join('data/images', str(product_id))
    if os.path.isdir(image_dir) and any(f.name.lower().endswith('.png') for f in os.scandir(image_dir) if f.is_file()):
      valid_ids.append(product_id)
    else:
      if os.path.isdir(image_dir) and not args.no_sanitize:
        shutil.rmtree(image_dir)
        invalid += 1

  if not args.no_sanitize:
    merged = merged[merged["id"].isin(valid_ids)]
    print(f'cleaned {invalid} invalid data')

  merged.to_csv(args.out)

  print(f'merged {len(dfs)} files for a total of {len(merged)}')
  
if __name__ == '__main__':
  entry()