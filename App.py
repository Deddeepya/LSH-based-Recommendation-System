from flask import Flask, render_template_string, request, jsonify, url_for
import json
import math

app = Flask(__name__)

# Load JSON file
with open("meta_Appliances.json", "r", encoding="utf-8") as f:
    products = [json.loads(line) for line in f]

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
                                <p class="fw-bold">{{ product.get('price', 'Price not available') }}</p>
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

    template = """
    <!doctype html>
    <html lang="en">
    <head>
        <title>{{ product.get('title', 'No Title') }}</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    </head>
    <body class="bg-light">
        <div class="container my-4">
            <a href="{{ url_for('home') }}" class="btn btn-secondary mb-3">⬅ Back to Products</a>
            <div class="card shadow p-4">
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
                        <p><strong>Price:</strong> {{ product.get('price', 'Not available') }}</p>
                        <p><strong>Date:</strong> {{ product.get('date', 'N/A') }}</p>

                        <h5>Features:</h5>
                        <ul>
                            {% for f in product.get('feature', []) %}
                                <li>{{ f }}</li>
                            {% endfor %}
                        </ul>

                        <h5>Description:</h5>
                        <p>{{ product.get('description', []) | join(' ') }}</p>

                        <h5>Rank:</h5>
                        <ul>
                            {% for r in product.get('rank', []) %}
                                <li>{{ r }}</li>
                            {% endfor %}
                        </ul>

                        <h5>Technical Details:</h5>
                        <pre>{{ product.get('tech1', 'N/A') }}</pre>

                        <h5>Other Details:</h5>
                        <ul>
                        {% for key, value in product.items() if key not in ['title','brand','asin','category','price','date','feature','description','rank','tech1','imageURLHighRes'] %}
                            <li><strong>{{ key }}:</strong> {{ value }}</li>
                        {% endfor %}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, product=product)


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
