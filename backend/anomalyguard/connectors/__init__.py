from .collector import Collector
from .opensearch import OpenSearchConnector
from .prometheus import PrometheusConnector
from .service_map import ServiceMap


def build_collector(prometheus_url, opensearch_url):
    service_map = ServiceMap.demo()
    return Collector([PrometheusConnector(prometheus_url, service_map), OpenSearchConnector(opensearch_url, service_map)])
