# Sähkövatkain

Sähkön hintaennuste ja lämmitystuntien vertailu Shelly Pro 3:lle.

GitHub Actions laskee ennusteen Shellyn lähettämillä KVS-asetuksilla. Nykyistä Shellyn lämmitysohjausta tai Watchdogia tämä projekti **ei muuta**.

## Ennustetiedostot

- `deploy/sahkovatkain.json`: yksityiskohtainen ennuste. Versio 3 lisää `rolling_plans`-kentän, jossa lämmityksen edullisimmat yksittäiset tunnit valitaan yhtenäisestä 24–120 tunnin aikaikkunasta. Valinta voi ylittää vuorokauden rajan. `selected` sisältää tuntien aloitusajat, hinnat ja tiedon siitä, onko kyse toteutuneesta hinnasta vai ennusteesta. `blocks` ryhmittelee peräkkäiset valitut tunnit.
- `deploy/sahkovatkain.txt`: vanhan muodon päiväkohtainen yhteenveto yhteensopivuutta varten.

Laskenta käyttää Shellyn `m2.c`-arvoa **päivittäisenä** tuntitarpeena. Esimerkiksi 4 h/vrk tarkoittaa 48 tunnin ikkunassa 8 halvinta tuntia, ei neljää. `complete=false` tarkoittaa, ettei koko tarkastelujaksolle ole riittävästi hintatietoja; sellaista suunnitelmaa ei saa tulkita täydelliseksi.

Hintavertailu käyttää toteutunutta pörssihintaa, kun se on saatavilla, muuten ennustetta, ja lisää nykyisen laskennan siirtotariffin. Siirtotariffin kausisäännöt ovat vielä koodiin määritettyjä eivätkä kaikki Shellyn KVS-parametrit ohjaa niitä.

**Huom:** `rolling_plans` on hintaperusteinen ennuste, ei valmis lämmityskäsky. Se ei vielä huomioi lämmityksen toteutuneita käyttötunteja, viimeisintä lämmityskertaa, lämpötilaa eikä lämmitysvälin takarajaa. Näitä ei pidä päätellä pelkästä `m2.c`-arvosta. Ennustetta ei ole kytketty releohjaukseen.
