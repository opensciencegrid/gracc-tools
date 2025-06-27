from opensearchpy import OpenSearch, RequestsHttpConnection
import re
import urllib3
import ssl # Required for creating an SSL context
import argparse # Import argparse for command-line arguments

# Suppress warnings for unverified HTTPS requests.
# WARNING: Setting verify_certs=False is NOT recommended for production environments.
# It makes your connection vulnerable to man-in-the-middle attacks.
# For production, ensure you have proper SSL certificate verification setup.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# OpenSearch cluster connection details
# Ensure the host and port are correct for your OpenSearch instance.
# The user provided https://gracc.opensciencegrid.org/q.
# OpenSearch client typically connects to the base URL, not a specific path like /q.
# We'll use the base host and standard HTTPS port.

def get_all_indices_and_aliases():
    """
    Fetches all indices and their associated aliases from the OpenSearch cluster.
    Returns a dictionary where keys are index names and values are their properties,
    including 'aliases'. Returns an empty dictionary on error.
    """
    print("\nFetching all indices and aliases...")
    try:
        # The 'feature' parameter can be used to request specific features like '_aliases'.
        # This gets comprehensive information about each index.
        response = client.indices.get(index='xrd-stash*')
        print(f"Successfully retrieved information for {len(response)} indices.")
        return response
    except Exception as e:
        print(f"Error fetching indices and aliases: {e}")
        return {}

def get_document_count(index_name):
    """
    Retrieves the document count for a given index.
    Returns the count as an integer, or -1 if an error occurs.
    """
    try:
        # Use the _count API to get the number of documents in an index
        response = client.count(index=index_name)
        return response.get('count', -1)
    except Exception as e:
        print(f"  > Error getting document count for '{index_name}': {e}")
        return -1

def cleanup_duplicate_indexes(os_client, dry_run=False):
    """
    Identifies and cleans up duplicate indices based on the 'xrd-stash-NNNNNN' pattern.
    Specifically:
    1. Finds pairs of 'xrd-stash-NNNNNN' (original) and 'xrd-stash-NNNNNN_shrunken' (shrunken).
    2. Checks if the document count of the original and shrunken index is the same.
    3. If the 'xrd-stash' alias points to the original index, it updates the alias
       to point to the shrunken version atomically.
    4. Deletes the original 'xrd-stash-NNNNNN' index.

    Args:
        os_client: An initialized OpenSearch client instance.
        dry_run (bool): If True, the script will only print the actions it would perform
                        without actually executing them.
    """
    if dry_run:
        print("\n--- Dry Run: No changes will be made to the OpenSearch cluster ---")
    else:
        print("\n--- Starting Duplicate Index Cleanup Process ---")

    indices_info = get_all_indices_and_aliases()
    if not indices_info:
        print("No index information retrieved. Skipping cleanup.")
        return

    # Store base original indices and their corresponding shrunken index names
    base_to_shrunken_map = {}

    # Regular expressions to identify original and shrunken indices
    base_index_pattern = re.compile(r'^(xrd-stash-\d{6})$')
    shrunken_index_pattern = re.compile(r'^(xrd-stash-\d{6})_shrunken$')

    # First pass: Categorize all existing indices
    original_indices_found = set()
    shrunken_indices_found = set()

    for index_name in indices_info.keys():
        if base_index_pattern.match(index_name):
            original_indices_found.add(index_name)
        elif shrunken_index_pattern.match(index_name):
            shrunken_indices_found.add(index_name)

    print(f"Identified {len(original_indices_found)} potential original indices ('xrd-stash-NNNNNN').")
    print(f"Identified {len(shrunken_indices_found)} potential shrunken indices ('xrd-stash-NNNNNN_shrunken').")

    # Second pass: Pair up original with shrunken versions
    for original_index in sorted(list(original_indices_found)): # Sort for consistent processing order
        shrunken_index_name = f"{original_index}_shrunken"
        if shrunken_index_name in shrunken_indices_found:
            base_to_shrunken_map[original_index] = shrunken_index_name
            print(f"  > Paired: '{original_index}' with '{shrunken_index_name}'")

    if not base_to_shrunken_map:
        print("\nNo matching original/shrunken index pairs found for cleanup. Nothing to do.")
        return

    # Determine all indices the 'xrd-stash' alias points to
    xrd_stash_alias_targets = []
    for index_name, details in indices_info.items():
        if 'aliases' in details and 'xrd-stash' in details['aliases']:
            xrd_stash_alias_targets.append(index_name)

    if xrd_stash_alias_targets:
        print(f"\nThe 'xrd-stash' alias currently points to indices: {xrd_stash_alias_targets}")
    else:
        print("\nThe 'xrd-stash' alias does not currently exist or point to any index.")

    # Process each identified pair for cleanup
    for original_index, shrunken_index in base_to_shrunken_map.items():
        print(f"\nProcessing pair: Original='{original_index}', Shrunken='{shrunken_index}'")

        # Step 1: Check document counts
        print(f"  > Checking document counts for '{original_index}' and '{shrunken_index}'...")
        original_doc_count = get_document_count(original_index)
        shrunken_doc_count = get_document_count(shrunken_index)

        if original_doc_count == -1 or shrunken_doc_count == -1:
            print(f"  > Skipping pair due to error retrieving document counts for '{original_index}' or '{shrunken_index}'.")
            continue
        elif original_doc_count != shrunken_doc_count:
            print(f"  > Document count mismatch: '{original_index}' has {original_doc_count} documents, "
                  f"while '{shrunken_index}' has {shrunken_doc_count} documents.")
            print(f"  > Skipping cleanup for this pair due to document count mismatch. "
                  f"Manual verification is recommended.")
            continue
        else:
            print(f"  > Document counts match: Both '{original_index}' and '{shrunken_index}' have {original_doc_count} documents.")

        # Step 2: Check and update the 'xrd-stash' alias if necessary
        # This logic ensures the alias is moved to the shrunken version before deleting the original
        if original_index in xrd_stash_alias_targets:
            print(f"  > 'xrd-stash' alias points to original index '{original_index}'.")
            if dry_run:
                print(f"  > Dry Run: Would update 'xrd-stash' alias from '{original_index}' to '{shrunken_index}'.")
            else:
                print(f"  > Attempting to update 'xrd-stash' alias...")
                try:
                    # Use the _aliases API for an atomic update (remove then add)
                    actions = {
                        "actions": [
                            {"remove": {"index": original_index, "alias": "xrd-stash"}},
                            {"add": {"index": shrunken_index, "alias": "xrd-stash"}}
                        ]
                    }
                    response = os_client.indices.update_aliases(body=actions)
                    if response.get('acknowledged', False):
                        print(f"  > Successfully updated 'xrd-stash' alias from '{original_index}' to '{shrunken_index}'.")
                        # Update our local tracking of where the alias points
                        xrd_stash_alias_targets.remove(original_index)
                        xrd_stash_alias_targets.append(shrunken_index)
                    else:
                        print(f"  > Failed to update 'xrd-stash' alias. Response: {response}")
                        # If alias update fails, it might be unsafe to delete the original index,
                        # as the alias might still be pointing to it.
                        print(f"  > Skipping deletion of '{original_index}' due to alias update failure.")
                        continue # Move to the next pair
                except Exception as e:
                    print(f"  > Error updating 'xrd-stash' alias: {e}")
                    print(f"  > Skipping deletion of '{original_index}' due to alias update error.")
                    continue # Move to the next pair
        elif shrunken_index in xrd_stash_alias_targets:
            print(f"  > 'xrd-stash' alias already points to shrunken index '{shrunken_index}'. No alias update needed for this pair.")
        else:
            print(f"  > 'xrd-stash' alias does not point to '{original_index}'. No alias update required for this specific pair related to 'xrd-stash'.")


        # Step 3: Delete the original index
        # We delete the original if its shrunken counterpart exists and (either the alias was updated
        # or it never pointed to the original index in the first place for this specific pair).
        print(f"  > Original index '{original_index}'.")
        if dry_run:
            print(f"  > Dry Run: Would delete index: '{original_index}'.")
        else:
            print(f"  > Attempting to delete the original index: '{original_index}'...")
            try:
                # Use ignore=[400, 404] to avoid exceptions if the index doesn't exist or other client-side errors occur
                response = os_client.indices.delete(index=original_index, ignore=[400, 404])
                if response.get('acknowledged', False):
                    print(f"  > Successfully deleted index: '{original_index}'.")
                else:
                    # If acknowledged is False but no exception, might be a non-error response from OS
                    print(f"  > Could not confirm deletion of index '{original_index}'. Response: {response}")
            except Exception as e:
                print(f"  > Error deleting index '{original_index}': {e}")

    if dry_run:
        print("\n--- Dry Run Completed: No changes were made to the OpenSearch cluster ---")
    else:
        print("\n--- Duplicate Index Cleanup Process Completed ---")

# Ensure the cleanup function is called when the script is executed
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean up duplicate OpenSearch indexes by migrating alias to shrunken index and deleting original."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run, printing actions without executing them."
    )
    parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="OpenSearch username."
    )
    parser.add_argument(
        "--password",
        type=str,
        required=True,
        help="OpenSearch password."
    )
    args = parser.parse_args()

    # Initialize the OpenSearch client with provided credentials
    opensearch_url = "https://gracc.opensciencegrid.org/q"  # Base URL for OpenSearch cluster
    client = OpenSearch(
        hosts=[opensearch_url],
        http_auth=(args.username, args.password),
        use_ssl=True,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False
    )

    # Test connection to the OpenSearch cluster
    print(f"Attempting to connect to OpenSearch cluster at {opensearch_url}...")
    try:
        # Use client.info() to get basic cluster information and verify connection
        info = client.info()
        print(f"Successfully connected to OpenSearch cluster: {info['cluster_name']}")
        print(f"Cluster Version: {info['version']['number']}")
    except Exception as e:
        print(f"Error connecting to OpenSearch: {e}")
        print("Please ensure:")
        print(f"  1. The OpenSearch cluster at {opensearch_url} is accessible.")
        print("  2. If authentication is required, update 'http_auth' with valid credentials.")
        print("  3. For production, consider proper SSL verification instead of 'verify_certs=False'.")
        exit() # Exit if connection fails, as further operations will not succeed


    cleanup_duplicate_indexes(client, dry_run=args.dry_run)
