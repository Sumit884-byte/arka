from arka.agent.data_collect import clean_text, duration_seconds
from arka.routing.symbolic import route_offline_extras


def test_duration_and_cleaning():
    assert duration_seconds("5m") == 300
    assert clean_text("<script>x</script> Hello   world") == "Hello world"


def test_collection_route():
    assert route_offline_extras("auto collect data about renewable energy for 2 minutes") == "data collect about renewable energy for 2 minutes"
