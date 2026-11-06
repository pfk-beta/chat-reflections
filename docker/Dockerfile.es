FROM docker.elastic.co/elasticsearch/elasticsearch:8.17.0
# icu: language-agnostic fallback; the rest: languages without a built-in analyzer
RUN bin/elasticsearch-plugin install --batch \
    analysis-icu analysis-stempel analysis-ukrainian analysis-kuromoji analysis-smartcn analysis-nori
