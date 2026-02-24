#!/usr/bin/env python3
"""
Tabelog scraper for Tokyo restaurants with 3.4+ rating
"""
import requests
from bs4 import BeautifulSoup
import time
import json
import re

def scrape_tabelog_tokyo(min_rating=3.4):
    """
    Scrape all Tokyo restaurants from Tabelog with rating >= min_rating
    """
    restaurants = []
    base_url = "https://tabelog.com/en/tokyo/rstLst/"
    
    # Tabelog search parameters for Tokyo, sorted by rating
    # We'll paginate through results
    params = {
        'SrtT': 'rt',  # Sort by rating
        'LstRange': 'SA',  # Search area
    }
    
    page = 1
    consecutive_fails = 0
    max_consecutive_fails = 3
    
    print(f"Starting Tabelog scrape for Tokyo restaurants (rating >= {min_rating})...")
    
    while consecutive_fails < max_consecutive_fails:
        try:
            # Build URL with page number
            url = f"{base_url}{page}/"
            print(f"\nPage {page}: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code != 200:
                print(f"  ❌ Status {response.status_code}")
                consecutive_fails += 1
                time.sleep(2)
                continue
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find restaurant listings
            listings = soup.find_all('li', class_='list-rst__item')
            
            if not listings:
                print(f"  ⚠️  No listings found on page {page}")
                consecutive_fails += 1
                time.sleep(2)
                continue
            
            print(f"  Found {len(listings)} listings")
            consecutive_fails = 0  # Reset on success
            
            page_added = 0
            for listing in listings:
                try:
                    # Extract rating
                    rating_elem = listing.find('span', class_='list-rst__rating-val')
                    if not rating_elem:
                        continue
                    
                    rating_text = rating_elem.text.strip()
                    rating = float(rating_text)
                    
                    # Skip if below threshold
                    if rating < min_rating:
                        print(f"  ⏹  Rating {rating} < {min_rating}, stopping pagination")
                        return restaurants
                    
                    # Extract name
                    name_elem = listing.find('a', class_='list-rst__rst-name-target')
                    if not name_elem:
                        continue
                    name = name_elem.text.strip()
                    url = 'https://tabelog.com' + name_elem['href']
                    
                    # Extract location/area
                    area_elem = listing.find('span', class_='list-rst__area')
                    area = area_elem.text.strip() if area_elem else 'Unknown'
                    
                    # Extract cuisine type
                    cuisine_elem = listing.find('span', class_='list-rst__genre')
                    cuisine = cuisine_elem.text.strip() if cuisine_elem else 'Unknown'
                    
                    restaurant = {
                        'name': name,
                        'rating': rating,
                        'area': area,
                        'cuisine': cuisine,
                        'url': url
                    }
                    
                    restaurants.append(restaurant)
                    page_added += 1
                    
                except Exception as e:
                    print(f"  ⚠️  Error parsing listing: {e}")
                    continue
            
            print(f"  ✅ Added {page_added} restaurants (total: {len(restaurants)})")
            
            # Check if there's a next page
            next_link = soup.find('a', class_='c-pagination__target--next')
            if not next_link or 'disabled' in next_link.get('class', []):
                print(f"  🏁 No more pages")
                break
            
            page += 1
            time.sleep(1)  # Be polite to Tabelog servers
            
        except Exception as e:
            print(f"  ❌ Error on page {page}: {e}")
            consecutive_fails += 1
            time.sleep(2)
    
    return restaurants

if __name__ == '__main__':
    restaurants = scrape_tabelog_tokyo(min_rating=3.4)
    
    print(f"\n{'='*60}")
    print(f"📊 RESULTS: Found {len(restaurants)} restaurants")
    print(f"{'='*60}")
    
    if restaurants:
        # Show rating distribution
        ratings = [r['rating'] for r in restaurants]
        print(f"\nRating range: {min(ratings):.1f} - {max(ratings):.1f}")
        print(f"Average: {sum(ratings)/len(ratings):.2f}")
        
        # Save to JSON
        output_file = 'tabelog_restaurants.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(restaurants, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Saved to {output_file}")
        
        # Show sample
        print(f"\nSample (first 5):")
        for r in restaurants[:5]:
            print(f"  {r['rating']:.1f} ⭐ {r['name']} ({r['area']})")
