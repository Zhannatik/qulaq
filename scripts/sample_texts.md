# Sample texts for the speech check

Invented announcements, no real people. Record each one as a normal WhatsApp voice note
on your phone (ideally one in a quiet room and one with background noise), then export the
chat with media. Save the same text as `ru.txt`, `kk.txt`, `mix.txt` to get an error rate.

## Russian (ru)

Уважаемые родители! В пятницу, 30 октября, в три часа дня в актовом зале состоится праздничный концерт. Детям нужна белая рубашка. Просьба до вторника сдать две тысячи тенге на подарки.

## Kazakh (kk)

Құрметті ата-аналар! Келесі жұма күні сағат он бесте мектепте мерекелік концерт өтеді. Балаларға ақ көйлек немесе ақ жейде кию керек. Қатысатындарыңызды сейсенбіге дейін жазып қалдырыңыздар.

## Mixed Kazakh and Russian (mix)

Ертең бесінші сабақтан кейін родительское собрание болады, просьба всем прийти. Сағат он сегізде, кабинет номер екі жүз бес.

## What to look at

- Are the dates, times, amounts and room numbers right? A few wrong letters matter less than a wrong date.
- Run once without `--lang` and once with `--lang Russian` or `--lang Kazakh` (the documented list of
  verified languages does not include them, so a bias value may be rejected; the server message is printed).
