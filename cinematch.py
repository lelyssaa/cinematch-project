import streamlit as st
import pandas as pd
import requests
from fuzzywuzzy import fuzz, process
import google.generativeai as genai
from datetime import datetime
import json
import time
import os

# Page configuration
st.set_page_config(
    page_title="🎬 Movie Recommender",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# DEFINE FUNCTIONS FIRST (before using them in session state initialization)
def load_favorites():
    """Load favorites from local storage file"""
    try:
        if os.path.exists('favorites.json'):
            with open('favorites.json', 'r') as f:
                return json.load(f)
    except:
        pass
    return []

def save_favorites():
    """Save favorites to local storage file"""
    try:
        with open('favorites.json', 'w') as f:
            json.dump(st.session_state.favorites, f)
    except:
        pass

def load_user_ratings():
    """Load user ratings from local storage file"""
    try:
        if os.path.exists('user_ratings.json'):
            with open('user_ratings.json', 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_user_ratings():
    """Save user ratings to local storage file"""
    try:
        with open('user_ratings.json', 'w') as f:
            json.dump(st.session_state.user_ratings, f)
    except:
        pass

def load_css(file_name):
    """Load CSS from external file"""
    try:
        with open(file_name, 'r') as f:
            return f.read()
    except FileNotFoundError:
        st.error(f"CSS file {file_name} not found!")
        return ""

def get_theme_css():
    """Get CSS based on current theme"""
    if st.session_state.dark_mode:
        return load_css('styles_dark.css')
    else:
        return load_css('styles_light.css')

# NOW Initialize session state (after functions are defined)
if 'recommendations' not in st.session_state:
    st.session_state.recommendations = []
if 'favorites' not in st.session_state:
    st.session_state.favorites = load_favorites()
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False
if 'user_ratings' not in st.session_state:
    st.session_state.user_ratings = load_user_ratings()

class MovieRecommender:
    def __init__(self):
        self.tmdb_api_key = None
        self.gemini_api_key = None
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"
        
        # Genre mapping (TMDB genre IDs)
        self.genres = {
            'Action': 28, 'Adventure': 12, 'Animation': 16, 'Comedy': 35,
            'Crime': 80, 'Documentary': 99, 'Drama': 18, 'Family': 10751,
            'Fantasy': 14, 'History': 36, 'Horror': 27, 'Music': 10402,
            'Mystery': 9648, 'Romance': 10749, 'Science Fiction': 878,
            'TV Movie': 10770, 'Thriller': 53, 'War': 10752, 'Western': 37
        }
        
        # Age rating mapping
        self.age_ratings = {
            'G': 'G', 'PG': 'PG', 'PG-13': 'PG-13', 'R': 'R', 'NC-17': 'NC-17'
        }

    def setup_apis(self, tmdb_key, gemini_key=None):
        """Setup API keys"""
        self.tmdb_api_key = tmdb_key
        if gemini_key:
            self.gemini_api_key = gemini_key
            genai.configure(api_key=gemini_key)

    def search_movies(self, query):
        """Search for movies using TMDB API"""
        if not self.tmdb_api_key:
            return []
        
        url = f"{self.base_url}/search/movie"
        params = {
            'api_key': self.tmdb_api_key,
            'query': query,
            'language': 'en-US'
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json().get('results', [])
        except requests.RequestException as e:
            st.error(f"Error searching movies: {e}")
            return []
    
    def get_movie_details(self, movie_id):
        """Get detailed movie information"""
        if not self.tmdb_api_key:
            return None
            
        url = f"{self.base_url}/movie/{movie_id}"
        params = {
            'api_key': self.tmdb_api_key,
            'append_to_response': 'watch/providers,release_dates,videos'
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            st.error(f"Error getting movie details: {e}")
            return None

    def get_age_rating_from_details(self, movie_details):
        """Extract age rating from movie details"""
        if not movie_details or 'release_dates' not in movie_details:
            return 'Not Rated'
        
        for country in movie_details['release_dates']['results']:
            if country['iso_3166_1'] == 'US':
                for release in country['release_dates']:
                    certification = release.get('certification')
                    if certification and certification.strip():
                        return certification
        return 'Not Rated'

    def get_movie_trailer(self, movie_id):
        """Get movie trailer URL"""
        if not self.tmdb_api_key:
            return None
            
        url = f"{self.base_url}/movie/{movie_id}/videos"
        params = {
            'api_key': self.tmdb_api_key,
            'language': 'en-US'
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            videos = response.json().get('results', [])
            
            # Find YouTube trailer
            for video in videos:
                if video.get('site') == 'YouTube' and video.get('type') == 'Trailer':
                    return f"https://www.youtube.com/embed/{video['key']}"
            
            return None
        except requests.RequestException as e:
            return None
    #movie trailer funct ends

    # PART 2: Fixed discover_movies method with age rating filter
    def discover_movies(self, genres=None, year=None, age_ratings=None, sort_by="popularity.desc", page=1):
        """Discover movies with filters"""
        if not self.tmdb_api_key:
            return []
            
        url = f"{self.base_url}/discover/movie"
        params = {
            'api_key': self.tmdb_api_key,
            'sort_by': sort_by,
            'page': page,
            'language': 'en-US'
        }
        
        if genres:
            genre_ids = [str(self.genres[g]) for g in genres if g in self.genres]
            if genre_ids:
                params['with_genres'] = ','.join(genre_ids)
        
        if year and year != "Any":
            params['year'] = year
        
        # Add age rating filter using certification
        if age_ratings:
            # Convert age ratings to TMDB certification format
            cert_mapping = {
                'G': 'G',
                'PG': 'PG',
                'PG-13': 'PG-13',
                'R': 'R',
                'NC-17': 'NC-17'
            }
            certifications = [cert_mapping.get(rating, rating) for rating in age_ratings]
            if certifications:
                params['certification_country'] = 'US'
                params['certification'] = '|'.join(certifications)
                
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            results = response.json().get('results', [])
            
            # Additional client-side filtering for age ratings if API filter didn't work
            if age_ratings and results:
                filtered_results = []
                for movie in results:
                    movie_details = self.get_movie_details(movie['id'])
                    if movie_details:
                        movie_age_rating = self.get_age_rating_from_details(movie_details)
                        if movie_age_rating in age_ratings or movie_age_rating == 'Not Rated':
                            filtered_results.append(movie)
                return filtered_results
            
            return results
        except requests.RequestException as e:
            st.error(f"Error discovering movies: {e}")
            return []

    #find similar movies funct begins
    def find_similar_movies(self, movie_title):
        """Find movies similar to the input movie"""
        # First, search for the movie
        search_results = self.search_movies(movie_title)
        if not search_results:
            return []
        
        # Get the first match
        movie_id = search_results[0]['id']
        
        # Get similar movies
        url = f"{self.base_url}/movie/{movie_id}/similar"
        params = {
            'api_key': self.tmdb_api_key,
            'language': 'en-US'
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json().get('results', [])
        except requests.RequestException as e:
            st.error(f"Error finding similar movies: {e}")
            return []

    def get_gemini_recommendations(self, description):
        """Use Gemini AI for word association recommendations"""
        if not self.gemini_api_key:
            st.warning("Gemini API key not provided. Skipping AI recommendations.")
            return []
        
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')  # Updated model name for free tier
            prompt = f"""
            Based on this description: "{description}"
            
            Recommend 10 movies that match this description or mood. 
            Return only movie titles, one per line, no explanations or numbering.
            Focus on popular, well-known movies that are likely to be in movie databases.
            """
            
            response = model.generate_content(prompt)
            movie_titles = [title.strip() for title in response.text.split('\n') if title.strip()]
            
            # Search for each recommended movie
            recommendations = []
            for title in movie_titles[:5]:  # Limit to 5 to avoid API limits
                movies = self.search_movies(title)
                if movies:
                    recommendations.extend(movies[:1])  # Take first match
            
            return recommendations
            
        except Exception as e:
            st.error(f"Error with Gemini AI: {e}")
            return []

    def get_streaming_providers(self, movie_id):
        """Get streaming providers for a movie"""
        if not self.tmdb_api_key:
            return []
            
        url = f"{self.base_url}/movie/{movie_id}/watch/providers"
        params = {'api_key': self.tmdb_api_key}
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Get US providers (you can modify for other countries)
            us_providers = data.get('results', {}).get('US', {})
            providers = []
            
            for provider_type in ['flatrate', 'rent', 'buy']:
                if provider_type in us_providers:
                    for provider in us_providers[provider_type]:
                        providers.append({
                            'name': provider['provider_name'],
                            'type': provider_type,
                            'logo': f"https://image.tmdb.org/t/p/w45{provider['logo_path']}"
                        })
            
            return providers
            
        except requests.RequestException as e:
            return []

    def format_movie_card(self, movie):
        """Format movie information for display"""
        poster_url = f"{self.image_base_url}{movie.get('poster_path', '')}" if movie.get('poster_path') else "https://via.placeholder.com/500x750?text=No+Poster"
        
        # Get additional details
        movie_details = self.get_movie_details(movie['id'])
        streaming_providers = self.get_streaming_providers(movie['id'])
        trailer_url = self.get_movie_trailer(movie['id'])
        
        rating = movie.get('vote_average', 0)
        year = movie.get('release_date', '')[:4] if movie.get('release_date') else 'N/A'
        
        # Age rating from movie details
        age_rating = 'Not Rated'
        if movie_details and 'release_dates' in movie_details:
            for country in movie_details['release_dates']['results']:
                if country['iso_3166_1'] == 'US':
                    for release in country['release_dates']:
                        if release.get('certification'):
                            age_rating = release['certification']
                            break
                    break
        
        return {
            'title': movie.get('title', 'Unknown Title'),
            'poster_url': poster_url,
            'year': year,
            'rating': rating,
            'age_rating': age_rating,
            'overview': movie.get('overview', 'No description available.'),
            'streaming_providers': streaming_providers,
            'trailer_url': trailer_url,
            'id': movie['id']
        }

def display_star_rating(movie_id, context="default"):
    """Display and handle star rating for a movie"""
    current_rating = st.session_state.user_ratings.get(str(movie_id), 0)
    
    st.write("**Your Rating:**")
    rating_cols = st.columns(5)
    
    for i in range(1, 6):
        with rating_cols[i-1]:
            # Add context to make keys unique across different sections
            unique_key = f"star_{movie_id}_{i}_{context}_{hash(str(movie_id) + context) % 10000}"
            if st.button("⭐" if i <= current_rating else "☆", 
                        key=unique_key, 
                        help=f"Rate {i} stars"):
                st.session_state.user_ratings[str(movie_id)] = i
                save_user_ratings()
                st.rerun()
    
    if current_rating > 0:
        st.write(f"You rated this: {'⭐' * current_rating} ({current_rating}/5)")

def export_favorites_to_csv():
    """Export favorites to CSV"""
    if st.session_state.favorites:
        df = pd.DataFrame(st.session_state.favorites)
        csv = df.to_csv(index=False)
        return csv
    return None

def main():
    # Apply external CSS
    css_content = get_theme_css()
    if css_content:
        st.markdown(f'<style>{css_content}</style>', unsafe_allow_html=True)
    
    # Header with theme toggle
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("🌓 Toggle Theme"):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()
    
    with col2:
        st.markdown("""
        <div class="main-header">
            <h1>🎬 Movie Recommendation Engine</h1>
            <p>Discover your next favorite movie with style!</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Initialize recommender
    recommender = MovieRecommender()
    
    # ============================================
    # 🔑 DEVELOPER: API KEYS FROM ENVIRONMENT
    # ============================================
    TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    # Check if API keys are loaded
    if not TMDB_API_KEY:
        st.error("❌ TMDB API key not found! Please check your keys.env file.")
        st.stop()
    
    # Setup APIs with your keys
    recommender.setup_apis(TMDB_API_KEY, GEMINI_API_KEY)
    
    # Main interface tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Smart Search", "🎯 Targeted Discovery", "🤖 AI Recommendations", "❤️ My Favorites"])
    
    with tab1:
        st.header("Find Movies Like...")
        similar_movie = st.text_input("Enter a movie you like:", placeholder="e.g., The Matrix, Inception, Titanic")
        
        if st.button("Find Similar Movies", key="similar_search") and similar_movie:
            with st.spinner("Searching for similar movies..."):
                recommendations = recommender.find_similar_movies(similar_movie)
                st.session_state.recommendations = recommendations
    
    with tab2:
        st.header("Discover Movies by Criteria")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Genre selection
            st.subheader("🎭 Genres")
            selected_genres = st.multiselect(
                "Select genres:",
                options=list(recommender.genres.keys()),
                default=[]
            )
            
            # Year selection
            st.subheader("📅 Release Year")
            current_year = datetime.now().year
            years = ["Any"] + list(range(current_year, 1950, -1))
            selected_year = st.selectbox("Select year:", years)
            
        with col2:
            # Age rating - FIXED
            st.subheader("🔞 Age Rating")
            selected_ratings = st.multiselect(
                "Select age ratings:",
                options=list(recommender.age_ratings.keys()),
                default=[]
            )
            
            # Sorting options
            st.subheader("📊 Sort by")
            sort_options = {
                "Popularity (High to Low)": "popularity.desc",
                "Popularity (Low to High)": "popularity.asc",
                "Rating (High to Low)": "vote_average.desc",
                "Rating (Low to High)": "vote_average.asc",
                "Release Date (Newest)": "release_date.desc",
                "Release Date (Oldest)": "release_date.asc",
                "Title (A-Z)": "title.asc",
                "Title (Z-A)": "title.desc"
            }
            selected_sort = st.selectbox("Sort by:", list(sort_options.keys()))
        
        if st.button("Discover Movies", key="discover_search"):
            with st.spinner("Discovering movies..."):
                recommendations = recommender.discover_movies(
                    genres=selected_genres,
                    year=selected_year if selected_year != "Any" else None,
                    age_ratings=selected_ratings,  # FIXED: Now passes age ratings
                    sort_by=sort_options[selected_sort]
                )
                st.session_state.recommendations = recommendations
    
    with tab3:
        st.header("AI-Powered Recommendations")
        st.write("Describe the kind of movie you're in the mood for, or just use random words!")
        
        description = st.text_area(
            "Movie description or keywords:",
            placeholder="e.g., 'dark sci-fi thriller with robots' or 'romantic comedy in Paris' or 'superhero action adventure'"
        )
        
        if st.button("Get AI Recommendations", key="ai_search") and description:
            with st.spinner("AI is thinking..."):
                recommendations = recommender.get_gemini_recommendations(description)
                st.session_state.recommendations = recommendations
    
    with tab4:
        st.header("❤️ My Favorite Movies")
        
        if st.session_state.favorites:
            # Export favorites
            col1, col2 = st.columns(2)
            with col1:
                csv_data = export_favorites_to_csv()
                if csv_data:
                    st.download_button(
                        label="📥 Export Favorites to CSV",
                        data=csv_data,
                        file_name="my_favorite_movies.csv",
                        mime="text/csv",
                        key="export_favorites_btn"  # FIXED: Added unique key
                    )
            with col2:
                if st.button("🗑️ Clear All Favorites", key="clear_favorites_btn"):  # FIXED: Added unique key
                    st.session_state.favorites = []
                    save_favorites()
                    st.rerun()
            
            st.divider()
            
            # Display favorites with FIXED unique keys
            for i, fav in enumerate(st.session_state.favorites):
                with st.container():
                    st.markdown('<div class="movie-card">', unsafe_allow_html=True)
                    col1, col2 = st.columns([1, 3])
                    
                    with col1:
                        st.image(fav['poster_url'], width=150)
                    
                    with col2:
                        st.subheader(f"{fav['title']} ({fav['year']})")
                        
                        # Rating and age rating
                        col_rating, col_age = st.columns(2)
                        with col_rating:
                            st.metric("⭐ TMDB Rating", f"{fav['rating']:.1f}/10")
                        with col_age:
                            st.metric("🔞 Age Rating", fav['age_rating'])
                        
                        # User rating - FIXED with context
                        display_star_rating(fav['id'], f"favorites_{i}")
                        
                        # Remove from favorites - FIXED with unique key
                        if st.button(f"💔 Remove from Favorites", key=f"remove_fav_{fav['id']}_{i}"):
                            st.session_state.favorites.pop(i)
                            save_favorites()
                            st.rerun()
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.divider()
        else:
            st.info("No favorites yet! Add some movies to your favorites from the search results.")
    
    # Display recommendations
    if st.session_state.recommendations:
        st.header("🎬 Recommended Movies")
        
         # FIXED: Add the filter section that was missing
        st.subheader("Filter Options")
        filter_col1, filter_col2 = st.columns(2)
        
        with filter_col1:
            show_trailers = st.checkbox("Show Trailers", value=False, key="show_trailers_checkbox")
            min_rating = st.slider("Minimum TMDB Rating", 0.0, 10.0, 0.0, 0.1, key="min_rating_slider")
        
        with filter_col2:
            max_results = st.selectbox("Maximum Results", [10, 20, 50, 100], index=1, key="max_results_select")
        
        # FIXED: Apply filters to create filtered_recommendations
        filtered_recommendations = []
        for movie in st.session_state.recommendations:
            if movie.get('vote_average', 0) >= min_rating:
                filtered_recommendations.append(movie)
        
        # Limit results
        filtered_recommendations = filtered_recommendations[:max_results]
        
        if not filtered_recommendations:
            st.info("No movies match your filters. Try adjusting the criteria.")
        else:
            st.write(f"Showing {len(filtered_recommendations)} movies:")
            
        # Display movie cards with FIXED unique keys
        for i, movie in enumerate(filtered_recommendations):
            movie_card = recommender.format_movie_card(movie)
            
            with st.container():
                st.markdown('<div class="movie-card">', unsafe_allow_html=True)
                col1, col2 = st.columns([1, 3])
                
                with col1:
                    st.image(movie_card['poster_url'], width=200)
                
                with col2:
                    st.subheader(f"{movie_card['title']} ({movie_card['year']})")
                    
                    # Rating and age rating
                    col_rating, col_age = st.columns(2)
                    with col_rating:
                        st.metric("⭐ TMDB Rating", f"{movie_card['rating']:.1f}/10")
                    with col_age:
                        st.metric("🔞 Age Rating", movie_card['age_rating'])
                    
                    # User rating - FIXED with context
                    display_star_rating(movie_card['id'], f"recommendations_{i}")
                    
                    # Overview
                    st.write("**Overview:**")
                    st.write(movie_card['overview'])
                    
                    # Trailer
                    if show_trailers and movie_card['trailer_url']:
                        st.write("**Trailer:**")
                        st.markdown(f'<div class="trailer-container"><iframe width="100%" height="315" src="{movie_card["trailer_url"]}" frameborder="0" allowfullscreen></iframe></div>', unsafe_allow_html=True)
                    
                    # Streaming providers
                    if movie_card['streaming_providers']:
                        st.write("**Available on:**")
                        provider_cols = st.columns(min(len(movie_card['streaming_providers']), 4))
                        for j, provider in enumerate(movie_card['streaming_providers'][:4]):
                            with provider_cols[j]:
                                st.write(f"• {provider['name']} ({provider['type']})")
                    else:
                        st.write("**Streaming availability:** Check local providers")
                    
                    # Action buttons - FIXED with unique keys
                    col_fav, col_details = st.columns(2)
                    with col_fav:
                        # Check if already in favorites
                        is_favorite = any(fav['id'] == movie_card['id'] for fav in st.session_state.favorites)
                        if not is_favorite:
                            if st.button(f"❤️ Add to Favorites", key=f"add_fav_{movie_card['id']}_{i}"):
                                st.session_state.favorites.append(movie_card)
                                save_favorites()
                                st.success("Added to favorites!")
                                st.rerun()
                        else:
                            st.success("✅ Already in favorites!")
                    
                    with col_details:
                        if st.button(f"📖 More Details", key=f"details_{movie_card['id']}_{i}"):
                            st.info(f"Visit TMDB: https://www.themoviedb.org/movie/{movie_card['id']}")
                
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()
        
        # Export recommendations - FIXED with unique key
        if st.button("📥 Export Recommendations", key="export_recommendations_btn"):
            df = pd.DataFrame([recommender.format_movie_card(movie) for movie in filtered_recommendations])
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name="movie_recommendations.csv",
                mime="text/csv",
                key="download_recommendations_btn"  # FIXED: Added unique key
            )

if __name__ == "__main__":
    main()
