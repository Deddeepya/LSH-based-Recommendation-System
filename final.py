from flask import Flask, render_template_string, request, jsonify, url_for
import json
import math
import re
import hashlib
import random
from collections import defaultdict
from typing import List, Set, Dict, Tuple

app = Flask(__name__)

# Load JSON file
with open("meta_Appliances.json", "r", encoding="utf-8") as f:
    products = [json.loads(line) for line in f]

# Data cleaning
def clean_text(text: str) -> str:
    # Remove HTML tags
    text = re.sub(r'<[^<]+?>', '', text)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Lowercase
    return text.lower()

def get_product_text(product: Dict, field: str) -> str:
    if field == 'title':
        return clean_text(product.get('title', ''))
    elif field == 'description':
        desc = product.get('description', [])
        if isinstance(desc, list):
            return ' '.join(clean_text(d) for d in desc)
        else:
            return clean_text(desc)
    elif field == 'hybrid':
        title = get_product_text(product, 'title')
        desc = get_product_text(product, 'description')
        return title + ' ' + desc
    return ''

# Shingling
def get_shingles(text: str, k: int = 3) -> Set[str]:
    if not text or text.isspace():  # Check for empty string or only spaces
        return set()
    if len(text) < k:
        return set([text])
    return set(text[i:i+k] for i in range(len(text) - k + 1))

# MinHash
class MinHash:
    def __init__(self, n_hashes: int = 100, seed: int = 42):
        random.seed(seed)
        self.n_hashes = n_hashes
        self.a = [random.randint(1, 2**32 - 1) for _ in range(n_hashes)]
        self.b = [random.randint(0, 2**32 - 1) for _ in range(n_hashes)]
        self.prime = 2**61 - 1  # Large Mersenne prime

    def compute_hi(self, r: int) -> List[int]:
        return [(self.a[i] * r + self.b[i]) % self.prime for i in range(self.n_hashes)]

# LSH
class LSH:
    def __init__(self, n_hashes: int, bands: int, rows: int):
        assert n_hashes == bands * rows
        self.bands = bands
        self.rows = rows
        self.buckets = [defaultdict(list) for _ in range(bands)]

    def add(self, item_id: str, signature: List[int]):
        for band_idx in range(self.bands):
            start = band_idx * self.rows
            end = start + self.rows
            band = tuple(signature[start:end])
            bucket_key = hash(band)
            self.buckets[band_idx][bucket_key].append(item_id)

    def query(self, signature: List[int]) -> Set[str]:
        candidates = set()
        for band_idx in range(self.bands):
            start = band_idx * self.rows
            end = start + self.rows
            band = tuple(signature[start:end])
            bucket_key = hash(band)
            if bucket_key in self.buckets[band_idx]:
                candidates.update(self.buckets[band_idx][bucket_key])
        return candidates

# Jaccard Similarity
def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union

# Precompute data
def prepare_data(k_shingle: int = 3, n_hashes: int = 100, bands: int = 20, rows: int = 5, seed: int = 42):
    asin_to_product = {p['asin']: p for p in products if 'asin' in p}
    asin_to_shingles = {'title': {}, 'description': {}, 'hybrid': {}}
    lshs = {'title': LSH(n_hashes, bands, rows), 'description': LSH(n_hashes, bands, rows), 'hybrid': LSH(n_hashes, bands, rows)}
    asin_to_signature = {'title': {}, 'description': {}, 'hybrid': {}}

    for asin, product in asin_to_product.items():
        for field in ['title', 'description', 'hybrid']:
            text = get_product_text(product, field)
            shingles = get_shingles(text, k_shingle)
            asin_to_shingles[field][asin] = shingles

    # For each field, compute MinHash signatures using row-major pseudo-code
    for field in ['title', 'description', 'hybrid']:
        # Collect unique shingles and map to indices (rows)
        all_shingles = set()
        for shingles in asin_to_shingles[field].values():
            all_shingles.update(shingles)
        shingle_list = list(all_shingles)
        shingle_to_index = {sh: idx for idx, sh in enumerate(shingle_list)}

        # Map shingles to list of asins (columns that have 1 in that row)
        shingle_to_asins = defaultdict(list)
        for asin, shingles in asin_to_shingles[field].items():
            for sh in shingles:
                shingle_to_asins[sh].append(asin)

        # Map asins to column indices
        asins = list(asin_to_shingles[field].keys())
        asin_to_index = {asin: idx for idx, asin in enumerate(asins)}
        num_columns = len(asins)

        # Initialize MinHash and signature matrix M (n_hashes rows, num_columns columns)
        minhasher = MinHash(n_hashes, seed)
        M = [[minhasher.prime + 1] * num_columns for _ in range(n_hashes)]

        # Follow pseudo-code: for each row r (shingle)
        for sh in shingle_list:
            r = shingle_to_index[sh]
            # Compute hi(r) for all hash functions
            h_values = minhasher.compute_hi(r)
            # For each column c that has 1 in row r
            for asin in shingle_to_asins[sh]:
                c = asin_to_index[asin]
                # For each hash function i
                for i in range(n_hashes):
                    if h_values[i] < M[i][c]:
                        M[i][c] = h_values[i]

        # Extract signatures for each asin
        for asin in asins:
            c = asin_to_index[asin]
            signature = [M[i][c] for i in range(n_hashes)]
            asin_to_signature[field][asin] = signature
            lshs[field].add(asin, signature)

    return asin_to_product, asin_to_shingles, lshs, asin_to_signature

# Precompute at startup
asin_to_product, asin_to_shingles, lshs, asin_to_signature = prepare_data()

# Home page (grid view with pagination + search bar)
@app.route("/")
def home():
    per_page = 40
    page = request.args.get("page", 1, type=int)
    total_pages = math.ceil(len(products) / per_page)

    start = (page - 1) * per_page
    end = start + per_page
    page_products = products[start:end]

    template = """
    <!doctype html>
    <html lang="en">
    <head>
        <title>Product Listing</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
        <style>
            .image-box {
                height: 250px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #f8f9fa;
                font-size: 14px;
                color: #666;
            }
            .image-box img {
                max-height: 100%;
                max-width: 100%;
                object-fit: contain;
            }
            #suggestions {
                position: absolute;
                background: white;
                border: 1px solid #ddd;
                max-height: 200px;
                overflow-y: auto;
                width: 100%;
                z-index: 1000;
            }
            #suggestions div {
                padding: 8px;
                cursor: pointer;
            }
            #suggestions div:hover {
                background: #f0f0f0;
            }
        </style>
    </head>
    <body class="bg-light">
        <div class="container my-4">
            <h2 class="mb-4">Product Listing</h2>

            <!-- Search Bar -->
            <div class="mb-4 position-relative">
                <input type="text" id="search" class="form-control" placeholder="Search product by title...">
                <div id="suggestions"></div>
            </div>

            <!-- Product Grid -->
            <div class="row g-4">
                {% for product in products %}
                    <div class="col-md-3">
                        <div class="card h-100 shadow-sm">
                            <div class="image-box">
                                {% if product.get('imageURLHighRes') %}
                                    <img src="{{ product.imageURLHighRes[0] }}" alt="Product Image">
                                {% else %}
                                    <span>No Image Available</span>
                                {% endif %}
                            </div>
                            <div class="card-body">
                                <h6 class="card-title">{{ product.get('title', 'No Title') }}</h6>
                                <p class="text-muted">{{ product.get('brand', 'Unknown') }}</p>
                                <p class="fw-bold">
                                  {% if product.get('price', '').startswith('$') %}
                                    {{ product['price'] }}
                                  {% endif %}
                                </p>
                                <a href="{{ url_for('product_detail', asin=product.asin) }}" class="btn btn-primary btn-sm">View Details</a>
                            </div>
                        </div>
                    </div>
                {% endfor %}
            </div>

            <!-- Pagination -->
            <nav class="mt-4">
                <ul class="pagination justify-content-center">
                    {% if page > 1 %}
                        <li class="page-item"><a class="page-link" href="{{ url_for('home', page=page-1) }}">Previous</a></li>
                    {% endif %}
                    <li class="page-item disabled"><a class="page-link">Page {{ page }} of {{ total_pages }}</a></li>
                    {% if page < total_pages %}
                        <li class="page-item"><a class="page-link" href="{{ url_for('home', page=page+1) }}">Next</a></li>
                    {% endif %}
                </ul>
            </nav>
        </div>

        <script>
        document.getElementById("search").addEventListener("input", function() {
            let query = this.value;
            let suggestionsBox = document.getElementById("suggestions");
            suggestionsBox.innerHTML = "";
            if (query.length < 2) return;

            fetch("/search?query=" + query)
                .then(res => res.json())
                .then(data => {
                    suggestionsBox.innerHTML = "";
                    data.forEach(item => {
                        let div = document.createElement("div");
                        div.textContent = item.title;
                        div.onclick = () => window.location.href = "/product/" + item.asin;
                        suggestionsBox.appendChild(div);
                    });
                });
        });
        </script>
    </body>
    </html>
    """
    return render_template_string(template, products=page_products, page=page, total_pages=total_pages)

# Product detail page
@app.route("/product/<asin>")
def product_detail(asin):
    product = next((p for p in products if p["asin"] == asin), None)
    if not product:
        return "Product not found", 404

    similarity_type = request.args.get("similarity", None)
    similar_products = []
    if similarity_type in ['pst', 'psd', 'pstd']:
        field_map = {'pst': 'title', 'psd': 'description', 'pstd': 'hybrid'}
        field = field_map[similarity_type]
        shingles = asin_to_shingles[field].get(asin, set())
        if shingles:
            sig = asin_to_signature[field].get(asin, [])
            candidates = lshs[field].query(sig)
            scores = []
            for cand in candidates:
                if cand != asin:
                    cand_shingles = asin_to_shingles[field].get(cand, set())
                    if cand_shingles:  # Check if candidate shingles are non-empty
                        jacc = jaccard_similarity(shingles, cand_shingles)
                        scores.append((cand, jacc))
            top_similar = sorted(scores, key=lambda x: -x[1])[:10]
            similar_products = [(asin_to_product.get(cand, {}), score * 100) for cand, score in top_similar]

    template = """
    <!doctype html>
    <html lang="en">
    <head>
        <title>{{ product.get('title', 'No Title') }}</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
        <style>
            .image-box {
                height: 300px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #f8f9fa;
            }
            .image-box img {
                max-height: 100%;
                max-width: 100%;
                object-fit: contain;
            }
            .similar-card .image-box {
                height: 150px;
            }
        </style>
    </head>
    <body class="bg-light">
        <div class="container my-4">
            <a href="{{ url_for('home') }}" class="btn btn-secondary mb-3">⬅ Back to Products</a>
            <div class="card shadow p-4 mb-4">
                <div class="row">
                    <div class="col-md-5">
                        <div class="image-box">
                            {% if product.get('imageURLHighRes') %}
                                <img src="{{ product.imageURLHighRes[0] }}" class="img-fluid">
                            {% else %}
                                <span>No Image Available</span>
                            {% endif %}
                        </div>
                    </div>
                    <div class="col-md-7">
                        <h3>{{ product.get('title', 'No Title') }}</h3>
                        <p><strong>ASIN:</strong> {{ product.get('asin', 'N/A') }}</p>
                        <p><strong>Brand:</strong> {{ product.get('brand', 'N/A') }}</p>
                        <p><strong>Category:</strong> {{ product.get('category', []) | join(' > ') }}</p>
                        <p><strong>Price:</strong> {% if product.get('price', '').startswith('$') %}
                                    {{ product['price'] }}
                                  {% else %}
                                    $
                                  {% endif %} </p>
                        <p><strong>Date:</strong> {{ product.get('date', 'N/A') }}</p>

                        <h5>Features:</h5>
                        <ul>
                            {% for f in product.get('feature', []) %}
                                <li>{{ f }}</li>
                            {% endfor %}
                        </ul>

                        <h5>Description:</h5>
                        <p>{{ product.get('description', []) | join(' ') }}</p>


                        <h5>Other Details:</h5>
                        <ul>
                        {% for key, value in product.items() if key in ['also_buy','also_view'] %}
                            <li><strong>{{ key }}:</strong> {{ value }}</li>
                        {% endfor %}
                        </ul>
                    </div>
                </div>
            </div>

            <!-- Similarity Options -->
            <h4 class="mb-3">Find Similar Products</h4>
            <div class="btn-group mb-4">
                <a href="{{ url_for('product_detail', asin=product.asin, similarity='pst') }}" class="btn btn-outline-primary">Products with Similar Title (PST)</a>
                <a href="{{ url_for('product_detail', asin=product.asin, similarity='psd') }}" class="btn btn-outline-primary">Products with Similar Description (PSD)</a>
                <a href="{{ url_for('product_detail', asin=product.asin, similarity='pstd') }}" class="btn btn-outline-primary">Products with Similar Title & Description (PSTD)</a>
            </div>

            {% if similar_products %}
                <h5>Top 10 Similar Products</h5>
                <div class="row g-4">
                    {% for sim_product, similarity_score in similar_products %}
                        <div class="col-md-3">
                            <div class="card h-100 shadow-sm similar-card">
                                <div class="image-box">
                                    {% if sim_product.get('imageURLHighRes') %}
                                        <img src="{{ sim_product.imageURLHighRes[0] }}" alt="Product Image">
                                    {% else %}
                                        <span>No Image</span>
                                    {% endif %}
                                </div>
                                <div class="card-body">
                                    <h6 class="card-title">{{ sim_product.get('title', 'No Title')[:50] }}...</h6>
                                    <p class="text-muted">Similarity: {{ '%.2f' % similarity_score }}%</p>
                                    <a href="{{ url_for('product_detail', asin=sim_product.asin) }}" class="btn btn-primary btn-sm">View Details</a>
                                </div>
                            </div>
                        </div>
                    {% endfor %}
                </div>
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(template, product=product, similar_products=similar_products)

# Search API (AJAX endpoint)
@app.route("/search")
def search():
    query = request.args.get("query", "").lower()
    results = []
    if query:
        for p in products:
            title = p.get("title", "")
            if query in title.lower():
                results.append({"asin": p.get("asin"), "title": title})
    return jsonify(results[:10])  # return top 10 matches

if __name__ == "__main__":
    app.run(debug=True)
