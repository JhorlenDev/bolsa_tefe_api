from geopy.geocoders import Nominatim

geolocator = Nominatim(user_agent="bolsa_tefe")

location = geolocator.geocode(
    "Rua Raimundo Lima, 274, Jerusalem, Tefé, AM",
    exactly_one=True,
    timeout=10
)

print(location)

if location:
    print(location.address)
    print(location.latitude)
    print(location.longitude)
else:
    print("Não encontrado")