from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "message": "Bienvenue sur le backend K-Albums!", 
        "status": "en fonctionnement",
        "info": "Ceci est un service hébergé sur Render."
    })

@app.route('/api/test')
def api_test():
    return jsonify({"message": "Réponse de test de l'API du backend!"})

# Cette partie ci-dessous n'est utile que si vous lancez app.py directement sur votre ordinateur pour tester.
# Render utilisera une autre commande (Gunicorn) pour lancer l'application.
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)