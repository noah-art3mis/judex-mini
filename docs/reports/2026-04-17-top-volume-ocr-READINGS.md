# Top-volume HC — leituras substantivas pós-OCR

Companion analítico do `SUMMARY.md` (que cobre o lado de engenharia:
25 URLs-alvo, 25 recuperados, 12 HCs, 2 passagens de OCR + uma rodada
manual para 3 falhas persistentes sob reuso de sessão). Este documento
registra **o que os textos efetivamente dizem** — as leituras
caso-a-caso das decisões monocráticas / acórdãos / manifestações da
PGR dos 12 HCs cobertos por este recorte, e o impacto da leitura no
diagnóstico do notebook `analysis/hc_top_volume.py`.

Enquanto o corpus "advocacia de ponta"
(`../2026-04-17-famous-lawyers-ocr/READINGS.md`) mapeia os nomes
consagrados (Toron, Pierpaolo, Vilardi, …) com ~3 HCs cada em média,
este recorte olha o oposto da curva: os **cinco impetrantes privados
de maior volume** — Victor Hugo Anuvale Rodrigues (91 HCs),
Cicero Salum do Amaral Lincoln (71), Luiz Gustavo Vicente Penna (61),
Mauro Atui Neto (54) e Fábio Rogério Donadon Costa (52). Todos
domiciliados em São Paulo (Tupã, Sertãozinho, Ribeirão Preto,
Presidente Prudente) e operando com uma cesta processual homogênea:
**tráfico de drogas de pequena a média monta**, preventivas convertidas
em flagrante, furto qualificado, ocasional estupro de vulnerável.

## Sumário do corpus textual

- **12 HCs** lidos, distribuídos entre os 5 impetrantes: Victor Hugo
  (4), Luiz Gustavo Penna (4), Fábio Donadon (3), Cícero Lincoln (1),
  Mauro Atui Neto (1).
- **25 PDFs substantivos** (decisão monocrática / acórdão / PGR) em
  `data/pdf/<sha1(url)>.txt.gz`.
- **Pré-OCR (pypdf):** 6/25 legíveis (>=5k chars) — todas as seis são
  **manifestações da PGR**. As decisões monocráticas e acórdãos são
  scans image-only.
- **Pós-OCR (2026-04-17):** 22/25 legíveis (>=3k chars). Três casos
  permanecem curtos (HC 138.757 monocrática 1928 chars, HC 134.855
  acórdão 2280 chars, HC 158.866 monocrática 3884 chars) — todos
  "genuinely-short orders" (despachos/ementas mínimas), não falha de
  extração.
- Os 5 impetrantes somam **329 HCs** no corpus judex-mini; dos 266
  com `outcome` preenchido, **218 (~82 %) são `nao_conhecido`** e
  **8 (~3 % do pool efetivo)** são `concedido`. A pergunta do
  notebook é se essas 8 concessões são vitórias defensivas reais ou
  apenas artefatos contábeis. A resposta, após leitura: **6 reais, 2
  recategorizáveis** — detalhes adiante.

## Parte I — Concessões (8 HCs)

### Victor Hugo · HC 134.507 · Maycon Douglas dos Santos Fernandes · Barroso · **concedido (vitória defensiva real)**
*Decisão monocrática, ~7,5 k caracteres. 27/06/2016.*

Tráfico de varejo em SP: preso em flagrante em 14/03/2015 com 2,02 g
de cocaína e 1,15 g de maconha. Juízo converteu em preventiva;
condenado a **2 anos e 6 meses em regime fechado** (art. 33 da Lei
11.343/06), vedado recorrer em liberdade. TJSP denegou HC; no STJ
(HC 355.275, Min. Joel Ilan Paciornik) a liminar foi indeferida.
Paciente já havia cumprido metade da pena em regime fechado.

**Ataque do impetrante:** regime inicial mais brando (HC 111.840
afastou a obrigatoriedade do fechado para crimes equiparados a
hediondos), substituição por restritivas (HC 97.256 afastou a vedação
do art. 44 da Lei de Drogas), ausência de fundamentação idônea para
manter a custódia, possibilidade de internação em clínica para
dependentes.

**Disposição do relator:** Barroso supera a Súmula 691 ("decisões de
Tribunal Superior manifestamente contrárias à jurisprudência do
STF"), **não conhece** do HC mas **concede a ordem de ofício**:
revoga a preventiva, fixa regime inicial **aberto**, manda o TJSP
examinar fundamentadamente a substituição da pena privativa por
restritivas. Cita o precedente próprio do pequeno tráfico como
"contraproducente do ponto de vista da política criminal".

Vitória defensiva real — paciente sai da cadeia e muda de regime.
Não é mera correção sumular porque há revogação da preventiva e
impacto executivo concreto.

### Victor Hugo · HC 173.170 · Rafael Ygor Dias Correia · Gilmar Mendes · **concedido (vitória defensiva real)**
*Decisão monocrática, ~19,4 k caracteres. 01/08/2019.*

Tráfico em Tupã/SP: preso em 07/06/2019 com ~258 g de cocaína e
~210 g de maconha em apartamento alugado; quatro autuados no total
(Rafael Ygor, Gabriel da Silva Barbosa, Luís Ricardo de Oliveira,
Carlos Alberto Martins Júnior), apreendidas balança, cheques e
celular. Juízo da Vara Criminal de Tupã converteu a prisão em
preventiva inferindo **organização criminosa** a partir da "renda
incompatível" e da gramagem. TJSP denegou. STJ (HC 519.119) indeferiu
a liminar.

**Ataque do impetrante:** falta de fundamentação idônea; paciente é
primário, trouxe comprovação de vínculo empregatício (eDOC 2); as
"ilações" do juízo sobre associação criminosa e coação de testemunhas
saltam para conclusões sem base concreta.

**Disposição do relator:** Gilmar supera a Súmula 691 ("hipótese
excepcional de flagrante constrangimento ilegal"), cita o HC 115.613
(Celso de Mello) sobre vedação do uso da preventiva como pena
antecipada e sobre a insuficiência da gravidade abstrata; acolhe o
dado concreto do vínculo empregatício, diferencia os dois
primários/sem-passagens (Rafael e Gabriel) dos dois com condenações
anteriores por tráfico (Luís Ricardo e Carlos Alberto) e **revoga a
preventiva** de Rafael e Gabriel, **substituindo por cautelares do
art. 319 do CPP**: comparecimento periódico, proibição de ausentar-se
da comarca, recolhimento noturno, proibição de contato com corréus.
Estende os efeitos via art. 580 CPP.

Vitória defensiva real, com extensão beneficiando corréu. Argumento
vencedor: estrutura diferencial entre réus dentro do mesmo flagrante.

### Cícero Lincoln · HC 138.847 · Fábio Vinicius Diniz · Barroso · **concedido (vitória defensiva real)**
*Decisão monocrática, ~6 k caracteres. 06/12/2016.*

Tráfico de varejo: preso em flagrante em 07/03/2016 com **27,090 g de
maconha e 4,020 g de cocaína**. Preventiva convertida pelo juízo de
origem; TJSP indeferiu liminar; STJ (HC 380.003, Min. Ribeiro Dantas)
também.

**Ataque do impetrante:** ausência dos requisitos do art. 312 CPP;
subsidiariamente, substituição por medida cautelar.

**Disposição do relator:** Barroso **não conhece** por ser HC
substitutivo de agravo regimental (falta pronunciamento colegiado no
STJ — cita HC 115.659/Fux, HC 122.166-AgR/Lewandowski), mas **concede
de ofício** o mesmo pacote do HC 134.507: paciente jovem (20 anos),
primário, bons antecedentes, preso por pequena quantidade — "decisão
genérica, fundada na gravidade abstrata do delito". Liberdade para
responder ao processo, facultadas as cautelares do art. 319 CPP.

Vitória defensiva real. Template-Barroso repetido do HC 134.507 — a
partir daqui a leitura se encurta: em qualquer caso de "tráfico,
pequena quantidade, paciente jovem e primário, decreto genérico",
Barroso aplica o mesmo protocolo.

### Luiz Gustavo Penna · HC 134.743 · André Luis Andrade Gonçalves · Marco Aurélio · **concedido (real, 3-2)**
*Liminar + manifestação da PGR + acórdão, ~25 k caracteres combinados. Liminar em 09/08/2016, acórdão em 08/08/2017.*

**Furto qualificado** (art. 155 §4º IV CP), concurso de pessoas:
preso em flagrante em 13/12/2015 em Sertãozinho/SP; paciente
**reincidente** em crimes contra o patrimônio. TJSP e STJ
(HC 357.948) denegaram, enfatizando periculosidade concreta e
má-folha.

**Ataque do impetrante:** falta de fundamentação, paciente viciado em
drogas (demandaria tratamento ambulatorial), antecipação de pena,
cautelares alternativas.

**Parecer da PGR** (Rodrigo Janot): opina pelo **não conhecimento** —
preventiva bem fundamentada na periculosidade social, paciente
contumaz em crimes patrimoniais; cita HC 133.685-AgR/Cármen sobre
dupla supressão de instância.

**Disposição do relator:** Marco Aurélio defere a liminar em
09/08/2016 por **excesso de prazo** — paciente preso há mais de seis
meses sem culpa formada, fundamento não enfrentado pelas instâncias
inferiores. No colegiado (08/08/2017, Primeira Turma), a ordem é
deferida **por maioria, vencidos Barroso e Rosa Weber**. Alexandre de
Moraes acompanhou Marco Aurélio ("crime sem violência ou grave ameaça,
mesmo se condenado já estaria fora do fechado"); Barroso divergiu
citando a reincidência e a narrativa do "furto de fios" com risco a
terceiros.

Vitória defensiva real, mas **frágil**: margem 3-2, fundamento
restrito ao excesso de prazo (não à falta de fundamentação em si), e
contra a opinião da PGR.

### Luiz Gustavo Penna · HC 135.060 · Lincoln Osmair Fedrigo · Barroso · **concedido (vitória defensiva real)**
*Decisão monocrática, ~5,8 k caracteres. 27/06/2016.*

Tráfico em SP: flagrante em 06/05/2016, **15 g de cocaína e 110 g de
maconha**. Preventiva convertida; TJSP e STJ (HC 359.841, Min.
Ribeiro Dantas) indeferiram.

**Ataque do impetrante:** ausência dos requisitos do art. 312 CPP.

**Disposição do relator:** Barroso repete o mesmo movimento do HC
138.847 — nega seguimento por ser substitutivo de agravo, concede de
ofício por falta de individualização no decreto e pequena quantidade,
liberdade para responder ao processo. **Mesmo dia, mesmo protocolo**
que o HC 134.507 (27/06/2016).

Vitória defensiva real. Terceira instância do template-Barroso
("pequeno tráfico + decreto genérico = liberdade").

### Luiz Gustavo Penna · HC 138.757 · Antonio Jorge Filho · Marco Aurélio · **concedido (real, 3-2, PGR a favor)**
*Liminar + PGR + acórdão, ~25 k caracteres combinados. Liminar em 05/12/2016, acórdão em 24/10/2017.*

Tráfico em Ribeirão Preto/SP: preso em 09/09/2016 por arts. 33 e 35
da Lei 11.343/06 (associação). Conforme os votos no colegiado, foram
apreendidas **55 porções de cocaína, balança de precisão e dinheiro**.
Juízo converteu a preventiva em "garantia da ordem pública" dada a
quantidade e o fato de estar desempregado. TJSP denegou liminar; STJ
(HC 377.104) indeferiu com base na Súmula 691.

**Ataque do impetrante:** gravidade abstrata não sustenta preventiva;
paciente primário, bons antecedentes, residência fixa, montador de
profissão afastado por motivo de saúde; eventual condenação implicaria
regime menos gravoso.

**Parecer da PGR:** opinou pela **concessão da ordem**.

**Disposição do relator:** Marco Aurélio defere liminar
monocraticamente ("a gravidade da imputação é insuficiente por si só";
"inexiste, no arcabouço normativo, a segregação automática"). No
colegiado, concede por maioria 3-2 (Marco Aurélio + Fux + Barroso;
vencidos Alexandre de Moraes e Rosa Weber). Barroso ressalva
"quantidades não relevantes de droga, sem características de integrar
organização criminosa"; Fux assenta que a hediondez foi o fundamento
e essa hediondez foi afastada pela jurisprudência.

Vitória defensiva real, novamente 3-2, e novamente contra o voto de
Alexandre de Moraes (que rejeitou: "55 porções, balança de precisão,
dinheiro — todas as características que não demonstram ser um usuário
e sim um traficante"). Concessão com PGR a favor — caso mais bem
apoiado do conjunto.

### Fábio Donadon · HC 134.651 · Luiz Carlos Moreti · Cármen Lúcia · **recategorizável como "procedural punt"**
*Acórdão + PGR, ~54 k caracteres combinados. 07/06/2016.*

**Roubo circunstanciado** em relojoaria de Tupã/SP na véspera do
Natal/2014: paciente preso preventivamente desde 31/12/2014,
identificado por funcionários da vítima e tendo joias subtraídas
encontradas em seu veículo; versão de coação rejeitada pelo juízo. Já
havia havido o **HC 131.204**, da mesma relatora, julgado pela
Segunda Turma em 15/12/2015, que denegara a ordem. Este HC 134.651 é
**reiteração pura** do anterior quanto aos requisitos da preventiva —
mesmos fatos, mesma causa de pedir — com uma única adição: **excesso
de prazo** na instrução criminal (preso havia mais de 16 meses sem
sentença).

**Ataque do impetrante:** requisitos da preventiva (reiteração do HC
131.204) + excesso de prazo.

**Parecer da PGR:** parecer pelo não conhecimento do writ
(reiteração) e pela concessão **de ofício apenas para mandar o STJ
analisar o excesso de prazo** — porque a Sexta Turma/STJ
(HC 346.766, Min. Nefi Cordeiro) havia equivocadamente assentado que
a matéria não fora decidida em segunda instância, quando o TJSP
tinha sim a analisado.

**Disposição da relatora:** Cármen Lúcia acolhe exatamente o parecer
da PGR. Por unanimidade (Gilmar, Cármen, Toffoli, Teori; ausente
Celso de Mello): **conhece em parte, denega na parte conhecida**
(prisão preventiva mantida), **concede de ofício** apenas para
**determinar à Sexta Turma do STJ que examine** a alegação de excesso
de prazo.

**Recategorização:** esta não é vitória defensiva. O paciente
continuou preso, a preventiva foi expressamente mantida, o STF apenas
devolveu a matéria ao STJ por erro processual daquela Corte. É um
**procedural punt** (reenvio técnico). O metadado `outcome=concedido`
reflete o verbo "conceder" no dispositivo, mas substantivamente o HC
foi denegado. Equivalente funcional do HC 138.862 de Toron (correção
sumular de regime) — só que aqui nem sequer houve correção
substantiva.

### Fábio Donadon · HC 143.345 · André Luiz Pereira da Luz · Marco Aurélio · **recategorizável como "correção sumular redundante"**
*Acórdão + PGR + monocrática, ~38 k caracteres combinados. 25/09/2018.*

Tráfico em Tupã/SP: paciente **condenado** (sentença transitada em
julgado na origem) a 5 anos de reclusão em regime fechado por tráfico
(art. 33 caput) + 1 ano por posse irregular de arma
(art. 12 Lei 10.826/03). TJSP manteve a sentença. No STJ
(HC 382.452/5ª Turma, Min. Felix Fischer), o writ foi inadmitido mas
**a ordem já tinha sido deferida de ofício para fixar regime inicial
semiaberto**.

**Ataque do impetrante:** (i) aplicação da causa de redução do art.
33 §4º da Lei de Drogas no patamar de 2/3; (ii) regime inicial
aberto; (iii) substituição da pena privativa por restritivas.

**Disposição do relator:** Marco Aurélio indefere a liminar em
17/05/2017 — não vê ilegalidade prima facie. No acórdão de
25/09/2018, por maioria (vencido Alexandre de Moraes; Fux não
participou), **defere a ordem unicamente para assentar o cabimento do
regime semiaberto**. Quanto ao §4º: apreensão de 68 porções
individuais de maconha caracteriza traficante "de porte maior";
fundamentação idônea. Quanto à substituição: pena acima dos 4 anos
impede (art. 44 I CP). Alexandre dissente ("mistura mais explosiva
que tem, condenação por tráfico com arma de fogo").

**Recategorização:** a concessão *reitera o que o STJ já havia
concedido* (regime semiaberto). **Nenhum ganho novo** para a defesa
vs. o que o réu já tinha quando o HC chegou ao STF. É correção
sumular redundante (Súmula 719/STF em substância), contra o voto de
Alexandre, 3-1. Classificar como "vitória" contamina a métrica.
Sugestão: recategorizar como **"confirmação de regime"**, não como
concessão substantiva. Paralelo funcional com o HC 138.862 de Toron
(Barroso, 2016).

## Parte II — Denegações (4 HCs de controle)

### Victor Hugo · HC 148.651 · Rafael Welington Pedro de Melo · Marco Aurélio · **denegado (4-1; relator reverte sua liminar)**
*Liminar + PGR + acórdão, ~45 k caracteres combinados. 10/10/2017 (liminar) → 11/12/2018 (colegiado).*

Tráfico em Tupã/SP: flagrante em 01/09/2017 com **16,84 g de crack**
em latinhas embaladas com fita crepe; residência já investigada
previamente. STJ (HC 417.122) indeferiu liminarmente.

**Ataque do impetrante:** gravidade abstrata, primariedade, ocupação
lícita, bons antecedentes, cautelares alternativas.

**Disposição do relator:** Marco Aurélio inicialmente **deferiu a
liminar** em 10/10/2017 com a fundamentação padrão ("hediondez e
malefícios do tráfico são elementos neutros"). Mas no colegiado, em
11/12/2018, a Primeira Turma **denega por maioria (vencido apenas
Barroso)** — e o próprio Marco Aurélio vota pela denegação,
tornando insubsistente a sua liminar: *"evoluo tendo em conta a
periculosidade, ao menos sinalizada … a inversão da ordem do
processo-crime foi justificada — evolução de entendimento"*. Barroso
é voto isolado pela concessão ("pequena quantidade de droga, não há
registro de reincidência"). Debate rico entre Barroso, Marco Aurélio
e Alexandre sobre política penal do tráfico ("general sem exército").

Denegação real — e **caso mais interessante doutrinariamente do
conjunto**: o único em que o próprio relator revê publicamente seu
entendimento entre liminar e mérito.

### Luiz Gustavo Penna · HC 134.855 · E.C.F. · Gilmar Mendes · **denegado (unânime)**
*Acórdão, ~2,3 k caracteres. 06/09/2016.*

**Estupro de vulnerável** (art. 217-A CP; paciente identificado só
pelas iniciais — provável réu em crimes sexuais contra menor).
Preventiva decretada; HC no STJ denegado.

**Ataque do impetrante:** ausência dos requisitos do art. 312 CPP.

**Disposição do relator:** Gilmar nega unanimemente (Segunda Turma:
Gilmar, Cármen, Toffoli, Teori; ausente Celso) — *"demonstrada a
necessidade da segregação cautelar para garantir a ordem pública e a
aplicação da lei penal"*. Ementa mínima, sem elaboração fática.

Denegação real. O único HC deste recorte em que o tipo penal é crime
sexual contra vulnerável — o corpus dominante é tráfico de varejo.
Mesmo padrão observado no corpus famous-lawyers (Toron/HC 230.210,
Alexandre de Moraes): ministros historicamente permeáveis não
concedem em crimes sexuais contra vulneráveis.

### Mauro Atui Neto · HC 158.866 · Mateus Gabriel Correa de Andrade · Alexandre de Moraes · **denegado (monocrática, Súmula 691)**
*Decisão monocrática, ~3,9 k caracteres. 28/06/2018.*

**Associação para o tráfico** (art. 35 Lei 11.343/06) em
Mairinque/SP. Denúncia descreve grupo estável com divisão de tarefas
operando nas imediações do "Bar do Bil" por ~12 meses; apreendidas ao
longo das incursões **798 porções de cocaína + 42 porções de maconha
+ 57 porções de crack**. TJSP denegou; STJ (HC 454.982, Min. Antonio
Saldanha Palheiro) indeferiu cautelar.

**Ataque do impetrante:** ausência dos pressupostos da custódia.

**Disposição do relator:** Alexandre de Moraes aplica estritamente a
Súmula 691 — *"não se constata a presença de flagrante ilegalidade"* —
e indefere monocraticamente com base no art. 21 §1º do RISTF. Sem
elaboração substantiva do mérito.

Denegação real. Este HC é o único de Mauro Atui Neto no recorte; o
padrão doutrinário é o inverso do corpus de Penna: associação para o
tráfico com estrutura coletiva documentada por 12 meses **não é caso
de "pequeno traficante"** nem candidato ao template-Barroso.

### Fábio Donadon · HC 134.444 · Júlio César Ramos da Silva · Dias Toffoli · **denegado (unânime, AgRg)**
*Decisão monocrática + acórdão do AgRg, ~25 k caracteres combinados. 11/05/2016 (monocrática) → 07/06/2016 (AgRg).*

Tráfico em SP: apreendidos em residência **232,73 g de maconha +
10,37 g de cocaína**, balança de precisão, sacos plásticos,
**mais de 2.000 pinos plásticos vazios** e quantia considerável em
dinheiro sem origem lícita. STJ (HC 352.736/5ª Turma, Min. Jorge
Mussi) não conheceu.

**Ataque do impetrante:** nulidade do auto de flagrante; falta de
fundamentação da preventiva; substituição por cautelares;
primariedade, residência fixa, trabalho lícito.

**Disposição do relator:** Toffoli denega monocraticamente (art. 192
RISTF) — grande quantidade de droga + apetrechos típicos de
mercancia + dinheiro sem origem = periculosidade concreta, precedente
HC 120.292/Fux. Nulidade do flagrante: supressão de instância (não
foi ao STJ); subsidiariamente, a conversão em preventiva torna
prejudicada a alegação. No AgRg (07/06/2016), Segunda Turma (Gilmar,
Cármen, Toffoli, Teori; ausente Celso) **nega provimento por
unanimidade**.

Denegação real. Contraponto direto ao HC 134.507 (também tráfico,
mesmo relator-pool) do mesmo corpus: a variável que muda o desfecho é
a **quantidade e o aparato de mercancia** (>2.000 pinos plásticos +
balança + dinheiro) — quando o flagrante documenta estrutura, o
template-defensivo "pequena-quantidade" não se aplica.

## Parte III — Síntese agregada

**Das 8 concessões metadadas, quantas são vitórias defensivas
reais?** Lendo os PDFs: **seis** (HC 134.507, HC 173.170, HC 138.847,
HC 134.743, HC 135.060, HC 138.757). **Duas recategorizáveis**:

- **HC 134.651 (Donadon · Cármen)** — procedural punt; o STF só
  mandou o STJ apreciar excesso de prazo; preventiva expressamente
  mantida; paciente continuou preso.
- **HC 143.345 (Donadon · Marco Aurélio)** — correção sumular
  redundante; STF apenas confirmou o regime semiaberto que o STJ já
  havia concedido de ofício.

Resultado substantivo: **6/52 ≈ 11,5 %** de vitórias defensivas
substantivas no top-5 volume, descontadas as duas pseudo-concessões.
A métrica bruta (8/52 ≈ 15,4 %) superestima em ~30 %.

### Top-3 teses recorrentes

1. **"Pequena quantidade de droga + paciente primário = preventiva
   injustificada"** (template Barroso; aparece em 134.507, 138.847,
   135.060, e é voto isolado mas substantivo em 148.651). Ataque
   padronizado contra decretos genéricos fundados em hediondez
   abstrata do tráfico. Invoca HC 97.256 (Ayres Britto —
   inconstitucionalidade do art. 44 da Lei de Drogas) e HC 111.840
   (Toffoli — inconstitucionalidade do regime fechado obrigatório). É
   o que mais ganha — e o que menos "advoga": é praticamente pleito
   de balcão contra fundamentação genérica.
2. **"Ausência de fundamentação idônea do art. 312 CPP"** (ortodoxia
   Marco Aurélio; aparece em 134.743 — excesso de prazo —, 138.757 e
   148.651). Invoca HC 115.613 (Celso de Mello) sobre vedação da
   preventiva como pena antecipada. Ganha quando há vulnerabilidade
   estrutural do decreto; perde quando há má-folha (148.651, em que o
   próprio Marco Aurélio reverte sua liminar).
3. **"Súmula 719/STF — regime inicial desproporcional à pena"**
   (HC 143.345). Ataque de dosimetria, já teria sido ganho no STJ; no
   STF só reitera. Quando aparece isolado (sem outras teses), a
   concessão é sumular/técnica, não defensiva.

### Como esse corpus difere do famous-lawyers

- **Tipo penal.** `famous-lawyers` é *white-collar* — lavagem,
  corrupção, fraude em OSCIPs, Lama Asfáltica, CPTM; `top-volume` é
  **tráfico de varejo a médio**, furto qualificado, ocasional estupro
  de vulnerável — crimes do cotidiano da advocacia criminal de
  interior.
- **Ataque dominante.** `famous-lawyers` ataca estrutura probatória
  (nulidade de interceptação, incompetência territorial, extensão
  entre turmas do STJ); `top-volume` ataca **fundamentação do decreto
  de preventiva** — argumento padronizado, quase uma petição-modelo.
- **Resultado.** ~6,7 % de vitória substantiva em famous-lawyers
  (Toron recategorizado) vs. ~11,5 % aqui. A leitura do diferencial
  é contra-intuitiva: o corpus do *top bar* perde mais, não por
  inferioridade advocatícia, mas porque entra em arena onde o STF
  aplica contenção Súmula-691 sistematicamente; o corpus
  `top-volume`, por estar em arena criminal ordinária, pega o
  *template-Barroso* e o *template-Marco-Aurélio* com relativa
  facilidade.

### A tese "HC-mill / near-zero grant rate" sobrevive?

**Parcialmente.** "Near-zero" é um exagero — o número bruto é 15 %,
e mesmo descontadas as pseudo-concessões é ~11,5 %, acima do
famous-lawyers.

Mas a leitura qualitativa sustenta a *substância* da tese original:
as concessões **não refletem qualidade advocatícia** — são o
pareamento estatístico de (a) alto volume de impetração em tráfico de
pequena monta com (b) a disponibilidade doutrinária de Barroso /
Marco Aurélio / Gilmar para conceder *qualquer* HC que encaixe no
template. O escritório de Luiz Gustavo Penna atinge 4 concessões não
porque ataca bem, mas porque **impetra muito e os casos caem
naturalmente no template**. Inversão do prêmio-advogado: aqui o
**prêmio-relator** é dominante.

### Tabela recategorizada

| HC      | impetrante       | outcome-bruto | leitura substantiva                                |
|---------|------------------|---------------|----------------------------------------------------|
| 134.507 | Victor Hugo      | concedido     | vitória defensiva real (template Barroso)          |
| 173.170 | Victor Hugo      | concedido     | vitória defensiva real (Gilmar — substantiva)      |
| 138.847 | Cícero Lincoln   | concedido     | vitória defensiva real (template Barroso)          |
| 134.743 | Luiz G. Penna    | concedido     | vitória defensiva real (excesso de prazo 3-2)      |
| 135.060 | Luiz G. Penna    | concedido     | vitória defensiva real (template Barroso)          |
| 138.757 | Luiz G. Penna    | concedido     | vitória defensiva real (3-2, PGR a favor)          |
| 134.651 | Fábio Donadon    | concedido     | **procedural punt — preventiva mantida**           |
| 143.345 | Fábio Donadon    | concedido     | **correção sumular redundante**                    |
| 148.651 | Victor Hugo      | denegado      | denegação real (Marco Aurélio reverte liminar)     |
| 134.855 | Luiz G. Penna    | denegado      | denegação real (estupro de vulnerável, Gilmar)     |
| 158.866 | Mauro Atui Neto  | denegado      | denegação real (assoc. tráfico com estrutura)      |
| 134.444 | Fábio Donadon    | denegado      | denegação real (tráfico com aparato)               |

**Taxa de vitória substantiva do top-5: 6/52 ≈ 11,5 %** (e não 15 %).

## Ressalvas de leitura

- **O texto extraído do PDF é ruidoso.** Vide nota equivalente em
  `../2026-04-17-famous-lawyers-ocr/READINGS.md`. Qualquer passo
  downstream de embedding / LLM deve re-chunkar, não ingerir cru.
- **A decisão monocrática parafraseia o impetrante.** O texto é a
  *reformulação do ministro* dos argumentos do advogado, não a
  petição em si.
- **Amostra controle é pequena.** 4 denegações não exploram toda a
  distribuição de derrotas do top-5 (que soma ~200+ denegações +
  ~45 não_providos). As denegações lidas aqui são um quadro
  ilustrativo, não um corte estatisticamente representativo.
- **Recategorização inviabiliza comparação cega com outros
  notebooks.** Se o notebook `hc_top_volume.py` for regenerado,
  vale filtrar as duas pseudo-concessões (HC 134.651 e HC 143.345)
  antes de reportar a fav_pct de Donadon.

## Apêndice — Links das peças e do processo

### Parte I — concessões

- **HC 134.507** · Victor Hugo · template Barroso · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4982084)
  - Decisão monocrática: [id=309867163](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309867163&ext=.pdf)
- **HC 173.170** · Victor Hugo · Gilmar — substantiva · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5729244)
  - Decisão monocrática: [id=15340728182](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15340728182&ext=.pdf)
  - Manifestação da PGR: [id=15340766504](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15340766504&ext=.pdf)
- **HC 138.847** · Cícero Lincoln · template Barroso · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5100814)
  - Decisão monocrática: [id=310925900](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310925900&ext=.pdf)
- **HC 134.743** · Luiz G. Penna · excesso de prazo (3-2) · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4989558)
  - Decisão monocrática: [id=310107338](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310107338&ext=.pdf)
  - Manifestação da PGR: [id=310477770](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310477770&ext=.pdf)
  - Inteiro teor do acórdão: [id=313088915](https://portal.stf.jus.br/processos/downloadPeca.asp?id=313088915&ext=.pdf)
- **HC 135.060** · Luiz G. Penna · template Barroso · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5001970)
  - Decisão monocrática: [id=309867171](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309867171&ext=.pdf)
- **HC 138.757** · Luiz G. Penna · concessão 3-2 com PGR a favor · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5097724)
  - Decisão monocrática: [id=310980826](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310980826&ext=.pdf)
  - Decisão monocrática: [id=312891778](https://portal.stf.jus.br/processos/downloadPeca.asp?id=312891778&ext=.pdf)
  - Manifestação da PGR: [id=311472232](https://portal.stf.jus.br/processos/downloadPeca.asp?id=311472232&ext=.pdf)
  - Inteiro teor do acórdão: [id=314202481](https://portal.stf.jus.br/processos/downloadPeca.asp?id=314202481&ext=.pdf)
- **HC 134.651** · Fábio Donadon · **procedural punt** · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4986813)
  - Manifestação da PGR: [id=309596987](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309596987&ext=.pdf)
  - Inteiro teor do acórdão: [id=309724638](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309724638&ext=.pdf)
- **HC 143.345** · Fábio Donadon · **correção sumular redundante** · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5178958)
  - Decisão monocrática: [id=311860541](https://portal.stf.jus.br/processos/downloadPeca.asp?id=311860541&ext=.pdf)
  - Manifestação da PGR: [id=311987277](https://portal.stf.jus.br/processos/downloadPeca.asp?id=311987277&ext=.pdf)
  - Manifestação da PGR: [id=15338910327](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15338910327&ext=.pdf)
  - Inteiro teor do acórdão: [id=15338853815](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15338853815&ext=.pdf)

### Parte II — denegações (controle)

- **HC 148.651** · Victor Hugo · Marco Aurélio reverte liminar · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5280048)
  - Decisão monocrática: [id=312986635](https://portal.stf.jus.br/processos/downloadPeca.asp?id=312986635&ext=.pdf)
  - Manifestação da PGR: [id=313060811](https://portal.stf.jus.br/processos/downloadPeca.asp?id=313060811&ext=.pdf)
  - Inteiro teor do acórdão: [id=15339844433](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15339844433&ext=.pdf)
- **HC 134.855** · Luiz G. Penna · estupro de vulnerável · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4993332)
  - Inteiro teor do acórdão: [id=310968554](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310968554&ext=.pdf)
- **HC 158.866** · Mauro Atui Neto · Alexandre · Súmula 691 · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5495915)
  - Decisão monocrática: [id=314742856](https://portal.stf.jus.br/processos/downloadPeca.asp?id=314742856&ext=.pdf)
- **HC 134.444** · Fábio Donadon · Toffoli · tráfico com aparato · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4980171)
  - Decisão monocrática: [id=309494040](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309494040&ext=.pdf)
  - Inteiro teor do acórdão: [id=309816943](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309816943&ext=.pdf)

> **Nota de acesso.** As URLs `downloadPeca.asp?id=…` funcionam em
> navegador; scripts sem cookies precisam passar por
> `src.scraping.scraper.fetch_pdf`. Mesmo shape usado em
> `tests/ground_truth/*.json` (`peticoes[].link`).
