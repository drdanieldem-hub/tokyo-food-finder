#!/usr/bin/env python3
"""
Full Tabelog scrape + Google Places cross-reference
"""
import requests
from bs4 import BeautifulSoup
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY')

def scrape_tabelog_page(page_num, min_rating=3.4):
    """Scrape a single page of Tabelog results"""
    url = f"https://tabelog.com/tokyo/rstLst/{page_num}/?SrtT=rt"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None, False
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find restaurant listings
        listings = soup.find_all('div', class_='list-rst')
        
        if not listings:
            return None, False
        
        restaurants = []
        should_continue = True
        
        for listing in listings:
            try:
                # Extract rating
                rating_elem = listing.find('span', class_='c-rating__val')
                if not rating_elem:
                    continue
                
                rating = float(rating_elem.text.strip())
                
                # Stop if below threshold
                if rating < min_rating:
                    should_continue = False
                    break
                
                # Extract name
                name_elem = listing.find('a', class_='list-rst__rst-name-target')
                if not name_elem:
                    continue
                
                name = name_elem.text.strip()
                
                # Extract area and genre (combined in one div)
                area_genre_elem = listing.find('div', class_='list-rst__area-genre')
                area_genre = area_genre_elem.text.strip() if area_genre_elem else ''
                
                # Try to split area and cuisine
                parts = area_genre.split('/')
                if len(parts) >= 2:
                    area = parts[0].strip()
                    cuisine = parts[1].strip()
                else:
                    area = area_genre
                    cuisine = ''
                
                address = area
                
                restaurants.append({
                    'name': name,
                    'tabelog_rating': rating,
                    'area': area,
                    'address': address,
                    'cuisine': cuisine
                })
                
            except Exception as e:
                continue
        
        return restaurants, should_continue
        
    except Exception as e:
        print(f"Error scraping page {page_num}: {e}")
        return None, False

def lookup_google_places(restaurant):
    """Look up restaurant on Google Places and get rating"""
    
    # Build search query
    query = f"{restaurant['name']} {restaurant['area']} Tokyo Japan"
    
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        'query': query,
        'key': GOOGLE_API_KEY,
        'region': 'jp',
        'language': 'en'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data['status'] == 'OK' and len(data['results']) > 0:
            # Take the first result
            place = data['results'][0]
            
            return {
                'google_rating': place.get('rating'),
                'google_user_ratings_total': place.get('user_ratings_total'),
                'google_place_id': place.get('place_id'),
                'google_name': place.get('name'),
                'lat': place['geometry']['location']['lat'],
                'lng': place['geometry']['location']['lng'],
                'google_address': place.get('formatted_address', '')
            }
        else:
            return None
            
    except Exception as e:
        print(f"  Google API error: {e}")
        return None

def main():
    print("="*60)
    print("TOKYO FOOD FINDER - Full Scrape")
    print("="*60)
    print("\nPhase 1: Scraping Tabelog (3.4+ rating)...")
    
    all_restaurants = []
    page = 1
    
    while True:
        print(f"\nPage {page}...", end=" ", flush=True)
        
        restaurants, should_continue = scrape_tabelog_page(page, min_rating=3.4)
        
        if restaurants is None:
            print("ERROR or no results")
            break
        
        if not restaurants:
            print("No more restaurants")
            break
        
        print(f"Found {len(restaurants)} restaurants")
        all_restaurants.extend(restaurants)
        
        if not should_continue:
            print("\n✅ Reached rating cutoff")
            break
        
        # Safety limit
        if page >= 100:
            print("\n⚠️  Safety limit reached (100 pages)")
            break
        
        page += 1
        time.sleep(1)  # Be polite to Tabelog
    
    print(f"\n{'='*60}")
    print(f"📊 Tabelog Results: {len(all_restaurants)} restaurants")
    print(f"{'='*60}")
    
    # Save intermediate results
    with open('tabelog_raw.json', 'w', encoding='utf-8') as f:
        json.dump(all_restaurants, f, ensure_ascii=False, indent=2)
    print("\n✅ Saved to tabelog_raw.json")
    
    print(f"\n{'='*60}")
    print("Phase 2: Cross-referencing with Google Places...")
    print(f"{'='*60}")
    
    enriched = []
    not_found = []
    
    for i, restaurant in enumerate(all_restaurants, 1):
        print(f"\n[{i}/{len(all_restaurants)}] {restaurant['name'][:40]}...", end=" ", flush=True)
        
        google_data = lookup_google_places(restaurant)
        
        if google_data and google_data['google_rating']:
            restaurant.update(google_data)
            enriched.append(restaurant)
            print(f"✅ Google: {google_data['google_rating']}⭐")
        else:
            not_found.append(restaurant)
            print("❌ Not found")
        
        # Rate limiting
        time.sleep(0.1)
        
        # Save progress every 100
        if i % 100 == 0:
            with open('progress.json', 'w', encoding='utf-8') as f:
                json.dump(enriched, f, ensure_ascii=False, indent=2)
            print(f"\n💾 Progress saved ({len(enriched)} enriched)")
    
    print(f"\n{'='*60}")
    print(f"📊 Google Places Results:")
    print(f"  Found: {len(enriched)}")
    print(f"  Not found: {len(not_found)}")
    print(f"{'='*60}")
    
    # Filter for 4.2+ Google rating
    filtered = [r for r in enriched if r.get('google_rating', 0) >= 4.2]
    
    print(f"\n{'='*60}")
    print(f"📊 Final Filtered Results (4.2+ Google rating):")
    print(f"  {len(filtered)} restaurants")
    print(f"{'='*60}")
    
    # Show rating distribution
    if filtered:
        ratings = [r['google_rating'] for r in filtered]
        print(f"\nGoogle Rating Range: {min(ratings):.1f} - {max(ratings):.1f}")
        print(f"Average: {sum(ratings)/len(ratings):.2f}")
    
    # Save final results
    with open('final_restaurants.json', 'w', encoding='utf-8') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Saved to final_restaurants.json")
    
    # Save not found for reference
    with open('not_found.json', 'w', encoding='utf-8') as f:
        json.dump(not_found, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Saved not-found list to not_found.json")
    
    print(f"\n{'='*60}")
    print("✅ COMPLETE!")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
