from opensearchpy import OpenSearch
import urllib3

# Suppress warnings for unverified HTTPS requests.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

host = 'gracc.opensciencegrid.org'
port = 443

client = OpenSearch(
    hosts=["https://gracc.opensciencegrid.org/q"],
    use_ssl=True,
    verify_certs=False,
    ssl_assert_hostname=False,
    ssl_show_warn=False
)

def print_xrd_stash_alias_indices():
    try:
        # Get all aliases named 'xrd-stash'
        aliases = client.indices.get_alias(name='xrd-stash')
        if not aliases:
            print("No indices found for alias 'xrd-stash'.")
            return
        print("Indices that alias 'xrd-stash' points to:")
        for index_name in aliases:
            print(f"  - {index_name}")
    except Exception as e:
        print(f"Error retrieving alias information: {e}")

if __name__ == "__main__":
    print_xrd_stash_alias_indices()
