"""What the dashboard receives, and the code that builds it.

Pure translation. Nothing here reads a database, calls the network or asks what time it
is -- it takes the objects the rest of the backend already produces and turns them into
the JSON the browser will parse. Phase 1 writes that JSON to a file; later the same
functions become the body of a Lambda, and the browser cannot tell the difference.
"""
