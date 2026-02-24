import requests
from bs4 import BeautifulSoup
import time

def count_tabelog_jp(min_rating=3.4):
    """
    Count restaurants on Japanese Tabelog (more comprehensive)
    """
    base_url = "https://tabelog.com/tokyo/rstLst/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    # First, check the main page to get total count
    print("Checking Japanese Tabelog for Tokyo restaurants...")
    
    try:
        url = f"{base_url}?SrtT=rt"  # Sort by rating
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Status {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for total count indicator
        # Japanese version shows: "○件中 1～20件"
        count_text = soup.find('span', class_='c-page-count__num')
        if count_text:
            total_text = count_text.text.strip()
            print(f"Total indicator: {total_text}")
        
        # Alternative: look in pagination
        page_info = soup.find('p', class_='c-pagination__total-result')
        if page_info:
            print(f"Pagination info: {page_info.text.strip()}")
        
        print("\n" + "="*60)
        
    except Exception as e:
        print(f"Error getting total: {e}")
    
    # Now do binary search to find cutoff
    # Japanese Tabelog likely has similar ~138k restaurants
    total_estimated = 150000  # Conservative estimate
    pages_total = total_estimated // 20
    
    print(f"Searching for 3.4+ rating cutoff...")
    print(f"Estimated pages to search: {pages_total:,}\n")
    
    low, high = 1, pages_total
    
    while low <= high:
        mid = (low + high) // 2
        url = f"{base_url}{mid}/?SrtT=rt"
        
        print(f"Page {mid:,}...", end=" ", flush=True)
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"ERROR {response.status_code}")
                high = mid - 1
                time.sleep(1)
                continue
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Japanese version uses same class for ratings
            ratings = []
            rating_elems = soup.find_all('span', class_='c-rating__val')
            
            if not rating_elems:
                # Try alternative selector
                rating_elems = soup.find_all('b', class_='c-rating__val')
            
            if not rating_elems:
                print("No ratings")
                high = mid - 1
                time.sleep(0.5)
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
                time.sleep(0.5)
                continue
            
            min_on_page = min(ratings)
            max_on_page = max(ratings)
            print(f"{max_on_page:.2f} - {min_on_page:.2f}")
            
            # Check if this page straddles the cutoff
            if min_on_page <= min_rating <= max_on_page:
                print(f"\n✅ Found cutoff at page {mid:,}")
                
                # Count restaurants above min_rating on this page
                above_cutoff = sum(1 for r in ratings if r >= min_rating)
                approximate_count = (mid - 1) * 20 + above_cutoff
                
                print(f"\n{'='*60}")
                print(f"📊 JAPANESE TABELOG: ~{approximate_count:,} restaurants rated {min_rating}+")
                print(f"{'='*60}")
                return approximate_count
                
            elif min_on_page > min_rating:
                low = mid + 1
            else:
                high = mid - 1
            
            time.sleep(0.5)
            
        except Exception as e:
            print(f"ERROR: {e}")
            high = mid - 1
            time.sleep(1)
    
    if high > 0:
        estimate = high * 20
        print(f"\n{'='*60}")
        print(f"📊 JAPANESE TABELOG: ~{estimate:,}+ restaurants rated {min_rating}+")
        print(f"{'='*60}")
        return estimate
    
    return None

if __name__ == '__main__':
    count_tabelog_jp(min_rating=3.4)
