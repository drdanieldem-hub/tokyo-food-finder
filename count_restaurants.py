import requests
from bs4 import BeautifulSoup
import time

def count_tabelog_restaurants(min_rating=3.4):
    """
    Binary search to find approximate count of restaurants above min_rating
    """
    base_url = "https://tabelog.com/en/tokyo/rstLst/"
    
    # Start by checking last page
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    # Tabelog shows 20 per page, total 138,335 restaurants
    total = 138335
    pages_total = (total // 20) + 1
    
    print(f"Total Tokyo restaurants: {total:,}")
    print(f"Total pages: {pages_total:,}")
    print(f"\nSearching for restaurants rated {min_rating}+...")
    
    # Binary search for the cutoff page
    low, high = 1, pages_total
    cutoff_page = None
    
    while low <= high:
        mid = (low + high) // 2
        url = f"{base_url}{mid}/?SrtT=rt"
        
        print(f"\nChecking page {mid:,}...", end=" ", flush=True)
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"ERROR {response.status_code}")
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all ratings on this page
            ratings = []
            rating_elems = soup.find_all('span', class_='list-rst__rating-val')
            
            if not rating_elems:
                print("No ratings found")
                high = mid - 1
                continue
            
            for elem in rating_elems:
                try:
                    rating = float(elem.text.strip())
                    ratings.append(rating)
                except:
                    pass
            
            if not ratings:
                print("No valid ratings")
                high = mid - 1
                continue
            
            min_on_page = min(ratings)
            max_on_page = max(ratings)
            print(f"Ratings: {max_on_page:.2f} - {min_on_page:.2f}")
            
            # Check if this page straddles the cutoff
            if min_on_page <= min_rating <= max_on_page:
                cutoff_page = mid
                print(f"\n✅ Found cutoff around page {cutoff_page:,}")
                
                # Count restaurants above min_rating on this page
                above_cutoff = sum(1 for r in ratings if r >= min_rating)
                approximate_count = (mid - 1) * 20 + above_cutoff
                
                print(f"\n{'='*60}")
                print(f"📊 ESTIMATE: ~{approximate_count:,} restaurants rated {min_rating}+")
                print(f"{'='*60}")
                return approximate_count
                
            elif min_on_page > min_rating:
                # All on this page are above cutoff, search higher
                low = mid + 1
            else:
                # All on this page are below cutoff, search lower
                high = mid - 1
            
            time.sleep(0.5)  # Be polite
            
        except Exception as e:
            print(f"ERROR: {e}")
            break
    
    # If we didn't find exact cutoff, estimate
    if high > 0:
        estimate = high * 20
        print(f"\n{'='*60}")
        print(f"📊 ESTIMATE: ~{estimate:,}+ restaurants rated {min_rating}+")
        print(f"{'='*60}")
        return estimate
    
    return None

if __name__ == '__main__':
    count_tabelog_restaurants(min_rating=3.4)
