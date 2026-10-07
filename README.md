# Sähkövatkain

Electricity price forecast and heating optimization for Shelly Pro 3.

Ensimmäinen testiversio hakee nordpool-predict-fi-ennusteen, lisää Oulun Seudun Sähkön kausisiirron ja laskee seuraaville viidelle kalenteripäivälle 8 halvimman tunnin keskihinnan. Tulos kirjoitetaan pieneen Shellylle sopivaan tiedostoon `deploy/sahkovatkain.txt`.

Nykyistä Shellyn lämmitysohjausta tämä repo ei muuta.
