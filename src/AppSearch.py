import random
import time
from google_play_scraper import app, search

class AppSearch:
    _lang, _country = "pt", "br"
    
    def __init__(self, number_reviews: int = 0):
        if number_reviews <= 0:
            print("WARN: Não foi cedido um número de reviews válido (maior que 0)")
        self.number_reviews = number_reviews
        
    def pause(self):
        """
        Intervalo aleatório entre requisições, para não sobrecarregar o servidor
        e não tomarmos rate limit gratuito
        """
        time.sleep(random.uniform(2, 5))
    
    def search(self, terms: list[str] = []):
        app_ids = self.search_terms(terms)
        app_results = []
        for app_id in app_ids:
            app_results.append(app(app_id, lang=self._lang, country=self._country))
            self.pause()
        return app_results
    
    def search_terms(self, terms: list[str]) -> list[str]:
        app_results = []
        
        for term in terms:
            app_results.extend([r["appId"] for r in search(term, lang=self._lang, country=self._country, n_hits=100)])
            self.pause()
        return app_results