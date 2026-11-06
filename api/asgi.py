from api.main import create_app

# Separate module so importing api.main (tests) never builds settings eagerly.
app = create_app()
