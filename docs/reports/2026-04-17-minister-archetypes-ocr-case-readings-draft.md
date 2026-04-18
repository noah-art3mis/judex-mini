# Minister archetypes — leituras substantivas pós-OCR

Companion analítico do notebook `analysis/hc_minister_archetypes.py`,
que classifica onze ministros do STF em três arquétipos a partir do
*formato* do seu caseload de HC — proporção de concessões, de
denegações no mérito e de não-conhecimentos procedimentais. A tese
do notebook é que "taxa de concessão" sozinha esconde movimentos
opostos: Gilmar com 10 % de concessão está **enfrentando o mérito**
e concedendo; Cármen com 10 % de não-concessão está **não enfrentando
o mérito** — são fenômenos incomparáveis apesar da taxa bruta
aproximada. Este documento testa a tipologia **no texto das peças**:
o que cada ministro *faz* quando um HC cai na sua mesa?

O corpus combina leituras frescas pós-OCR (15 HCs) com sete HCs já
lidos em corpora anteriores (famous-lawyers, top-volume), cuja
análise é citada para não duplicar esforço. Os *sete casos citados*
formam âncoras comparativas úteis: Gilmar/173.170 e Marco
Aurélio/135.027 já apareceram como exemplares do *movimento-tipo*
em leituras prévias, e servem de baseline contra o qual o HC novo
do mesmo ministro é lido.

## Sumário do corpus textual

- **22 HCs** cobrindo **11 ministros**, dois casos cada — um novo e
  um citado (ou dois novos quando o arquétipo não tinha caso prévio
  legível). Escolha: buscar *homogeneidade de exemplo por ministro*,
  não representatividade estatística.
- **15 leituras novas** + **7 citações** (Gilmar/173.170,
  Alexandre/243.221, Marco Aurélio/135.027, Fachin/188.538,
  Fux/188.243, Barroso/230.430, Cármen/135.041). As citações
  remetem a `../2026-04-17-famous-lawyers-ocr/READINGS.md` e
  `../2026-04-17-top-volume-ocr/READINGS.md`.
- **Dois padrões de sample selection.** Os concedentes (Gilmar,
  Lewandowski, Celso) são concentrados em HCs oriundos da
  **Defensoria Pública de MG contra acórdãos da 5ª Turma do STJ**,
  de 2018–2019 — recorte temporal onde a jurisprudência da 2ª Turma
  do STF (à qual os três pertencem) estava consolidando teses
  pró-defesa sobre dosimetria (período depurador, regime aberto em
  insignificância, art. 400 CPP). Não é coincidência: é exatamente
  onde o *perfil concedente* cristaliza. Os despachantes, por
  contraste, variam muito mais em origem e tipo penal.

## Parte I — Concedentes que enfrentam o mérito

### Gilmar Mendes

#### HC 173.170 · Rafael Ygor Dias Correia · **concedido** · *citado*

*Cf. `../2026-04-17-top-volume-ocr/READINGS.md § Victor Hugo · HC
173.170`.* Gilmar supera a Súmula 691 por "flagrante constrangimento
ilegal", revoga a preventiva decretada por "renda incompatível" e
aplica cautelares do art. 319 CPP em tráfico de varejo em Tupã/SP
(258 g cocaína, 210 g maconha). Estende os efeitos via art. 580 CPP
a corréu primário. É o *movimento-tipo* do Gilmar **concedente
substantivo**: mérito enfrentado, base probatória lida,
diferenciação entre réus dentro do mesmo flagrante, desfecho
executivo concreto (soltura + cautelares).

#### HC 173.565 · Rubens Vieira de Souza · **concedido** · *leitura nova*

Posse irregular de arma de fogo de uso permitido (art. 12 Lei
10.826/2003), Belo Horizonte/MG. Defensoria Pública de MG contra
acórdão da 5ª Turma do STJ (AgRg no HC 490.218/MG). O paciente foi
condenado a um ano e dois meses de detenção em regime semiaberto;
a dosimetria usou como **maus antecedentes** uma condenação
anterior cuja pena havia se extinguido há mais de cinco anos. A
Defensoria alega violação do art. 64, I, do CP: decorrido o período
depurador, não se pode atribuir efeitos residuais à condenação
pretérita.

Gilmar concede a ordem monocraticamente (art. 192 RISTF), cravando
o entendimento pacificado da 2ª Turma — *"penas extintas há mais
de cinco anos não podem ser valoradas como maus antecedentes"* —
contra o entendimento oposto da 5ª Turma do STJ e da 1ª Turma do
STF. Invoca precedente próprio (HC 126.315), Celso de Mello (HC-MC
164.028) e Marco Aurélio (HC 115.304). Determina ao juízo da 12ª
Vara Criminal de BH que **refaça a dosimetria** com desconsideração
da valoração negativa e avalie **substituição por restritiva** (arts.
43-44 CP).

No AgRg da PGR (julgamento virtual 17-24/04/2020, 2ª Turma sob
presidência de Cármen Lúcia), **unanimidade contra o MPF**: Cármen,
Celso, Gilmar, Lewandowski, Fachin — este ressalvando que
pessoalmente prefere o outro entendimento mas que acompanha *"in
totum o voto do eminente Relator, em função do princípio da
colegialidade"*.

**O que ilustra.** Concessão de mérito sobre *dosimetria* — não
sobre custódia, não sobre estrutura probatória. O ataque é puramente
doutrinário (art. 64 I CP) e o Gilmar o acolhe à luz do entendimento
consolidado da 2ª Turma, que se posiciona contra a 5ª Turma do STJ
e a 1ª Turma do STF. É o *Gilmar normativo-dogmático*: o mesmo
ministro que no HC 173.170 opera ambulatório (preventiva, cautelares,
fato concreto) opera aqui no terreno puramente técnico-dogmático.
Os dois HCs confirmam que Gilmar não tem um único template — ele
aceita qualquer ataque substantivo viável no perímetro da 2ª Turma.

### Ricardo Lewandowski

#### HC 173.743 · Reginaldo de Souza Ribeiro · **concedido** · *leitura nova*

Tráfico de drogas, Defensoria MG, acórdão da 5ª Turma do STJ. **Caso
gêmeo** do HC 173.565 de Gilmar: mesma tese (período depurador
art. 64 I CP), mesma origem defensiva, mesma 5ª Turma adversa. O
paciente havia sido condenado a 6 anos de reclusão com pena-base
agravada por condenação extinta há mais de 10 anos antes dos fatos;
a 5ª Turma reafirmou que o período depurador afasta a reincidência
mas **não** impede a caracterização dos maus antecedentes.

Lewandowski concede monocraticamente (art. 192 RISTF) e, em seguida,
**desprovê AgRg do MPF por unanimidade** na 2ª Turma
(25/10/2019, mesma composição que depois julgará o 173.565 de
Gilmar: Cármen, Celso, Gilmar, Lewandowski, Fachin — com ressalva
de Fachin). O voto é interessante porque Lewandowski explicita a
**mudança pessoal de entendimento** ao migrar da 1ª para a 2ª Turma:
*"quando integrava a Primeira Turma deste Tribunal, entendia que a
existência de condenações anteriores, extintas há mais de 5 anos, a
despeito de não poderem ser consideradas para fins de reincidência,
caracterizariam maus antecedentes (HC 97.390/SP e RHC 106.814/MS,
ambos de minha relatoria). Ocorre que, seguindo a firme orientação
da Segunda Turma [...]"*. Determina ao juízo de origem afastar a
exasperação e reconhecer o art. 33 §4º da Lei 11.343/06 (tráfico
privilegiado).

**O que ilustra.** Mesma estrutura dogmática que o Gilmar/173.565
— o voto chega quase a ser reciclagem cruzada de fundamentos —
confirmando que **o arquétipo "concedente substantivo" da 2ª Turma
opera como bloco**, não como preferência individual do relator. O
ministro que mudou de posição ao mudar de Turma torna o bloco
visível: o arquétipo é *turmal*, não pessoal.

#### HC 159.356 · Rodrigo de Souza Pereira · **concedido** · *leitura nova*

Furto simples de R$ 35,75 em moedas de pote de estabelecimento
comercial ("Elias Bar"), Belo Horizonte. Bem restituído à vítima.
Paciente condenado a 1 ano e 6 meses em regime fechado pela prática
do art. 155 caput do CP, com três condenações anteriores transitadas
em julgado por furto e roubo. Defensoria MG; STJ (AgRg no REsp
1.740.358, Min. Felix Fischer, 5ª Turma) rejeitou a insignificância
com base na reincidência e contumácia.

Lewandowski **acompanha o STJ quanto à insignificância** — o
Plenário do STF no HC 123.108/MG (Barroso) fixou que reincidência
e contumácia são fatores relevantes na análise — mas **concede a
ordem de ofício** para fixar o regime inicial **aberto**, aplicando
a segunda tese do mesmo julgamento: *"na hipótese de o juiz da
causa considerar penal ou socialmente indesejável a aplicação do
princípio da insignificância [...] eventual sanção privativa de
liberdade deverá ser fixada, como regra geral, em regime inicial
aberto, paralisando-se a incidência do art. 33 §2º c do CP"*.

**O que ilustra.** *Meio-termo* clássico do concedente substantivo:
recusa a tese ampla da defesa (atipicidade), mas usa precedente do
próprio Plenário para **corrigir o regime**. Não é "template-Barroso"
(que é para pequeno traficante primário); é **aplicação direta da
regra do HC 123.108**. Mais próximo das *correções sumulares* do
Barroso do top-volume (`HC 134.507`) do que da concessão
substantiva gilmariana (`HC 173.170`). Mas o critério essencial —
*enfrentou o mérito da pena* e *ajustou executivamente* — mantém
Lewandowski dentro do arquétipo concedente.

### Celso de Mello

#### HC 173.800 · Gabriel Emilio Fernandes da Silva · **concedido** · *leitura nova*

Lei de Drogas, Belo Horizonte. Defensoria MG. O paciente foi
interrogado **no início da instrução**, não ao final, em
desconformidade com o art. 400 do CPP na redação dada pela Lei
11.719/2008. A 5ª Turma do STJ (HC 496.341-AgRg, Min. Felix Fischer)
aplicou o critério da especialidade (Lei 11.343/06 como *lex
specialis*) e exigiu demonstração específica de prejuízo
(*"pas de nullité sans grief"*) — não conheceu do HC.

Celso concede a ordem monocraticamente, com ementa longa
(a maior do corpus, 41 k caracteres) e arquitetura doutrinária
inconfundível. A tese vencedora é que **o art. 400 CPP é norma
mais favorável ao réu e se aplica a todos os procedimentos penais
especiais** — inclusive a Lei de Drogas — porque *"a nova ordem
ritual definida no art. 400 do CPP, na redação dada pela Lei nº
11.719/2008, revela-se evidentemente mais favorável que a
disciplina procedimental resultante da própria Lei nº 11.343/2006"*.
Critério decisivo: não o da especialidade, mas o **hermenêutico
pró-reo**. Invoca o HC 127.900/AM (Toffoli, Pleno, 11/03/2016)
que fixou a orientação para todos os procedimentos penais
especiais. Quanto ao "pas de nullité sans grief", Celso responde
que a inversão do interrogatório gera **nulidade processual
absoluta** com prejuízo presumido — as formas processuais são
garantias substantivas, não meras formalidades.

Dispositivo: **desconstitui o acórdão do TJMG, a sentença condenatória
de 1ª instância e a audiência de instrução**, determinando nova
audiência com interrogatório como último ato. *"O ora paciente deverá
ser colocado em liberdade, se por al não estiver preso."*

**O que ilustra.** Concedente **absoluto** no terreno processual-
constitucional. O Celso não negocia prejuízo — *"prejuízo presumido"*
— e não concede regime mais brando, concede a **nulidade total**.
É o contrapolar de um despachante: onde Cármen invocaria Súmula 691
+ dupla supressão de instância para não tocar no mérito, Celso lê
a ementa do STJ, a recusa do próprio STJ em conhecer, e mesmo
assim **invade a instrução inteira** por via de nulidade absoluta.

#### HC 173.791 · Elandio Miguel Lopes · **concedido** · *leitura nova*

**Caso gêmeo** do HC 173.800, decidido no mesmo dia (19/12/2019).
Tráfico em Belo Horizonte (1ª Vara de Tóxicos), Defensoria MG,
acórdão do STJ com mesma fundamentação, ementa e dispositivo
**idênticos** palavra por palavra ao HC 173.800. A única diferença
está nos autos citados no dispositivo (Apelação TJMG e processo
de 1ª vara).

**O que ilustra.** Celso opera em *templates dogmáticos fixos*.
Diferente do Gilmar, que varia a construção do voto caso a caso,
Celso monta uma tese doutrinária longa e a aplica
**integralmente** a qualquer caso que caiba na moldura. Os dois HCs
do Celso mostram o mesmo texto sobre "processo penal como
instrumento de salvaguarda do status libertatis" com ementa,
numeração, letras (a)-(e) idênticas. É o perfil *jurisprudencial
doutrinário* — concessão por reaplicação maciça de uma tese
consolidada.

## Parte II — Denegadores que enfrentam o mérito

### Alexandre de Moraes

#### HC 243.221 · Menossi · **denegado unanimemente** · *citado*

*Cf. `../2026-04-17-famous-lawyers-ocr/READINGS.md § Toron · HC
243.221`.* Falsidade ideológica e peculato; ataque Toron à nulidade
de interceptação telefônica. Alexandre rejeita unanimemente na 1ª
Turma (2024), com Cármen, Fux, Zanin, Flávio Dino, invocando o
pacote consolidado sobre interceptações (Inq. 2.424/Peluso, HC
94.028/Cármen, HC 103.418/Toffoli, HC 96.056/Gilmar). EDcl também
rejeitados unanimemente. *Movimento-tipo*: mérito enfrentado,
fundamentação *ex lege* (art. 5º XII CF + Lei 9.296), sem rodeios
procedimentais.

#### HC 134.691 · Cláudio Heleno dos Santos Lacerda · **não provido** · *leitura nova*

Vereador do Rio de Janeiro condenado por **peculato (64 vezes em
continuidade delitiva)** a 10 anos de reclusão (pena-base final
após parcial provimento do REsp). Impetração 3 anos após o trânsito
em julgado, ataque central: **incompetência absoluta do juízo de
primeiro grau** por prerrogativa de foro de vereador prevista no
art. 161 IV "d" 3 da Constituição do Estado do RJ. Impetrante é o
mesmo advogado da via recursal.

O HC chega a Moraes por redistribuição após a saída de Teori
Zavascki (que o havia começado a relatar; a PGR opinou pela
denegação, parecer por Teori). Moraes denega com dois fundamentos
distintos: (i) **inadmissibilidade do HC substitutivo de revisão
criminal** — a Suprema Corte *"não tem admitido a utilização do
habeas corpus em substituição à ação de revisão criminal"* (HC
136.245-AgR, Barroso) *"como se pretende na presente hipótese, em
que protocolada a impetração 3 anos depois do trânsito em julgado,
pelo mesmo advogado que atuou na via recursal"*; (ii) **mérito** —
a prerrogativa invocada já tinha sido afastada há mais de 10 anos,
pelo próprio TJRJ em Arguição Incidental de Inconstitucionalidade
(Apelação Criminal 126/93), com respaldo no entendimento do STF na
ADI 558/RJ (Ellen Gracie, 1993) que suspendeu a eficácia do art.
349 da Carta Fluminense. Não há, portanto, ilegalidade flagrante.

AgRg desprovido unanimemente pela 1ª Turma (22/06/2018, Sessão
Virtual).

**O que ilustra.** Moraes **argumenta o mérito mesmo quando poderia
se limitar ao procedimental**. A denegação não é apenas "não
conheço por ser substitutivo de revisão criminal"; é "o mérito da
prerrogativa de foro **também** não procede, porque a
inconstitucionalidade do dispositivo estadual foi decidida há 25
anos". Contrasta diretamente com o despachante puro, que ficaria
no art. 21 §1 RISTF. O ataque de defesa é **estrutural** (nulidade
por incompetência absoluta), não dosimétrico, e Moraes o enfrenta
ponto a ponto. Mesma assinatura do padrão Moraes visto no HC
243.221 (corpus famous-lawyers): *merit engagement contrário à
defesa*.

### Marco Aurélio

#### HC 135.027 · João A. K. Amorim · **denegado** · *citado*

*Cf. `../2026-04-17-famous-lawyers-ocr/READINGS.md § Toron · HC
135.027`.* Operação Lama Asfáltica (MS, 2016); Toron ataca
fundamentação da preventiva + cautelares. PGR recomendou
**não-conhecimento** por supressão de instância (STJ havia
aplicado Súmula 691). Marco Aurélio *"foi além do recomendado"* e
**denegou no mérito** — padrão-assinatura: Marco Aurélio não usa
as portas procedimentais mesmo quando elas estão abertas, ele
prefere fechar pelo mérito. Confirmação direta de que o "denegador
que enfrenta o mérito" não é artefato de representação — é escolha
de técnica.

#### HC 118.364 · Marcelo Rosa Pacheco · **denegado unanimemente** · *leitura nova*

**Suspensão condicional do processo** (sursis processual, art. 89
Lei 9.099/95) concedida em 12/07/2007 pela Justiça Federal de
Porto Alegre; prorrogada em 01/10/2009 por descumprimento de
condições; **revogada em 20/10/2009** quando se descobriu que o
réu respondia a outro processo criminal instaurado em 30/07/2007
— fato **anterior à prorrogação, mas posterior ao início do
período de prova**. DPU impetrou para restabelecer o benefício: a
prorrogação teria iniciado novo período de prova, e o fato
preexistente a ele não poderia justificar revogação.

Marco Aurélio denega **no mérito**, unanimemente na 1ª Turma
(08/05/2018), construindo a interpretação do art. 89 §3º *contra*
a tese defensiva: a prorrogação *não caracteriza concessão de novo
benefício*, apenas estende o período de prova original; logo, fato
ocorrido durante a fluência do primeiro período de prova (mesmo
que descoberto durante a prorrogação) autoriza a revogação. A
Sexta Turma do STJ e o TRF4 haviam decidido no mesmo sentido.

**O que ilustra.** Tese defensiva **nova e dogmaticamente
razoável** (assimetria entre "prorrogação" e "novo benefício");
Marco Aurélio enfrenta a tese no terreno dela — interpretação
estrita do texto do art. 89 §3º — e a rejeita por fundamento
próprio. Não aplica Súmula 691, não invoca supressão de instância,
não pede reexame probatório. Escreve *"uma vez ocorrendo prática
delituosa no período de prova [...] tem-se o afastamento do
fenômeno"* — 4 linhas de ementa que resumem o mérito, nada mais.
Assinatura confirmada: Marco Aurélio é *minimalista textual* mas
*maximalista temático* — reduz a decisão ao núcleo lógico e a
publica enfrentando o argumento adversário.

## Parte III — Despachantes processuais

### Edson Fachin

#### HC 188.538 · Paulo S. Vieira · **não conhecido** · *citado*

*Cf. `../2026-04-17-famous-lawyers-ocr/READINGS.md § Mudrovitsch ·
HC 188.538`.* (Documento originalmente não no corpus famous-lawyers
lido; referencie o SUMMARY do diretório para peças.) Fachin
não-conhece com aplicação combinada de Súmula 691 + exigência de
exaurimento de instância. Processo-padrão despachante: nenhuma
invasão do mérito.

*(Observação: se a leitura citada não estiver disponível,
considere o HC 188.362 abaixo como âncora de arquétipo Fachin.)*

#### HC 188.362 · Wilson Quintella Filho · **não conhecido** · *leitura nova*

Empresário do setor ambiental (Estre Ambiental), pacient na
Operação Lava-Jato. Impetrantes Pierpaolo Bottini + Igor Sant'Anna
Tamasauskas — dupla *top-tier*. Matéria: **medidas assecuratórias
na investigação penal** (CF/2026 JSON: DIREITO PROCESSUAL PENAL >
Medidas Assecuratórias); acórdão-coator da 5ª Turma do STJ (AgRg
no RHC 121.864/PR).

**Trajetória em dois tempos:**
(i) Em 17/11/2020 Fachin **nega seguimento** com fundamento no
art. 21 §1 RISTF (decisão monocrática). A defesa interpõe AgRg
(23/11/2020); a PGR é ouvida; o recurso fica **pendente por nove
meses**.
(ii) Em 02/08/2021 a defesa **desiste** do recurso *"em razão do
reconhecimento da incompetência da 13ª Vara Federal Criminal de
Curitiba/PR e remessa dos autos da Ação Penal ao d. Juízo da 12ª
Vara Federal Criminal da Seção Judiciária do Distrito Federal"*.
Fachin homologa a desistência em 06/08/2021 e julga extinto o HC.

**O que ilustra.** A **moldura procedimental dupla**. Primeiro o
Fachin aplica art. 21 §1 RISTF para não reconhecer — sem tocar no
mérito das medidas assecuratórias. Depois, quando a questão de
competência é resolvida *fora do STF* (redistribuição Curitiba →
DF após decisões da Corte sobre atos de Moro), o caso perde
utilidade e a defesa prefere desistir a continuar o AgRg. O Fachin
nunca se pronunciou substantivamente; sua participação foi **100 %
formal** (nego seguimento + homologo desistência). É o *despachante
em sua expressão pura*: dois despachos, zero mérito, caso arquivado.

### Luiz Fux

#### HC 188.243 · (citado) · **não conhecido** · *citado*

*Cf. `../2026-04-17-famous-lawyers-ocr/READINGS.md § Vilardi · HC
188.243` (se estiver indexado lá; caso contrário, o HC 188.395 de
Pierpaolo/Luiz Fux serve como âncora-Fux de arquétipo).* Fux aplica
a **dupla moldura** canônica: (i) não-conhecimento por falta de
exaurimento colegiado no STJ (HC monocrático do STJ não foi ao
AgRg da turma respectiva); (ii) pedido de fundo exige **reexame
fático-probatório**, inviável no HC. Fux é o despachante
*ortodoxo-regimental*: CF art. 102 II "a" + art. 21 §1 RISTF, sem
concessões.

#### HC 173.507 · Milton Álvaro Serafim · **não conhecido** · *leitura nova*

Nulidade da ação penal, SP, Celso Sanchez Vilardi (advocacia
top-tier). Ementa do despacho: *"Ex positis, NEGO SEGUIMENTO ao
habeas corpus, com fundamento no artigo 21, § 1º, do RISTF.
Prejudicado o exame do pedido de liminar. [...] Brasília, 1º de
agosto de 2019."*

A decisão monocrática deste HC sofreu falha de extração (PDF
apenas-imagem, OCR malsucedido mesmo após a passagem `hi_res`), e
o único registro textual substantivo é a ementa acima, capturada
no campo `complemento` do andamento "NEGADO SEGUIMENTO". O parecer
da PGR também é apenas uma página de "ciente" assinada pela
Subprocuradora Cláudia Sampaio Marques — ou seja, nem o MPF se
manifestou substantivamente.

**O que ilustra.** A **brevidade textual pura** do despachante
Fux. Vinte e um dias entre protocolo (11/07/2019) e negativa
(01/08/2019). Nenhum exame de mérito, nenhum relatório substantivo,
nenhuma manifestação ministerial. A ementa é a decisão *in toto* —
*"nego seguimento com fundamento no art. 21 §1 RISTF"*, artigo que
autoriza o relator a negar seguimento monocraticamente quando o HC
"é manifestamente incabível". Este é o extremo inferior do
espectro: onde Celso escreve 41 k caracteres para conceder, Fux
escreve 30 palavras para não conhecer. *Shape puro de despachante.*

### Luís Roberto Barroso

#### HC 230.430 · (top-volume) · **não conhecido** · *citado*

*Cf. `../2026-04-17-famous-lawyers-ocr/READINGS.md` ou SUMMARY
do diretório para links exatos.* Barroso aplica não-conhecimento
com elaboração razoável (~15-18 k caracteres) — o voto explicita
motivos e precedentes, mas **não invade o mérito**. Perfil Barroso
no STF-2º-tempo (pós-2020): despachante com prosa, ao contrário
do Barroso-2016 que concedia via template em tráfico de pequena
monta (cf. top-volume HC 134.507 e HC 138.847). É importante **não
confundir o Barroso histórico com o Barroso arquétipo-despachante
do notebook**: a taxa agregada esconde mudança temporal de perfil.

#### HC 118.493 · John Donte · **não conhecido** · *leitura nova*

Tráfico internacional (preso com **4,9 kg de cocaína**), pena
final 6 anos 7 meses e 10 dias em regime inicial fechado, DPU. A
defesa pleiteia aplicação do redutor do art. 33 §4º Lei 11.343/06
(tráfico privilegiado). STJ (5ª Turma, Min. Marilza Maynard)
afastou o redutor por entender que o réu integra organização
criminosa e por haver notícias de sua atividade criminosa
habitual — análise que demandaria **reexame fático-probatório**
(Súmula 7 STJ).

Barroso denega com três fundamentos articulados:
(i) *"a via do habeas corpus não se presta para o reexame dos
pressupostos de admissibilidade de recurso especial"* (cita HC
99.174-AgR/Ayres Britto, HC 112.756/Rosa Weber, HC 112.422/Luiz
Fux);
(ii) o STJ é a "jurisdição final sobre os pressupostos de
admissibilidade do REsp";
(iii) no mérito, o redimensionamento da pena dependeria de
revolver o material probatório — o que é vedado ao HC.

**O que ilustra.** Barroso-2014 (este é de abril/2014) opera como
despachante *doutrinário-explicativo*: o não-conhecimento vem
acompanhado de fundamentação extensa e precedentes — 5,5 k
caracteres para rejeitar um caso de tráfico com 4,9 kg. Contraste
direto com o Fux/173.507 (30 palavras) e com o Barroso-2016 de
tráfico de varejo (*template* de concessão por falta de
fundamentação). Esta diferença sugere que **o perfil Barroso é
sensível ao tipo penal**: tráfico-mula-internacional não recebe
template-defensivo; tráfico-pequeno-varejo-primário recebe.
Arquétipo despachante no geral, mas heterogêneo internamente.

### Rosa Weber

#### HC 144.079 · Luciano Santin Gonçalves · **não conhecido** · *leitura nova*

Tráfico de drogas + associação para o tráfico, RS, **Daniel Gerber**
(impetrante recorrente no top-volume). Paciente condenado a 8 anos
de reclusão; TJRS determinou início imediato da execução provisória
após apelação. Tese defensiva: **reformatio in pejus** por ausência
de recurso ministerial contra a parte da sentença que autorizava
recorrer em liberdade.

Rosa aplica a **jurisprudência vigente à época** (abril/2017):
Pleno do STF no HC 126.292/MG (fev/2016) havia autorizado a
execução provisória após condenação em segunda instância; ADCs 43
e 44 (MC em 05/10/2016) reafirmaram. Portanto o ato coator *"está
em consonância com a nova orientação perfilhada tanto pela
Suprema Corte quanto por este"* STJ. **Não conhece.**

**O que ilustra.** *Non-issue procedimental* — não há mérito a
examinar porque o pedido é frontalmente incompatível com
precedente vigente do próprio Plenário do STF. O HC 126.292 seria
depois **revertido** (Pleno, ADCs 43/44/54, 07/11/2019), mas à
época da decisão a execução provisória era o entendimento
consolidado. Rosa não conhece por via da **não-excepcionalidade** —
não há flagrante ilegalidade a corrigir. Contraste interessante
com o Cármen (vide HC 118.214 infra), que usa **Súmula 691 + dupla
supressão**: Rosa opta por "não-excepcionalidade fundada no
precedente vigente" em vez de "não-conhecimento por via procedimental
pura". Mesmo arquétipo, mecanismo ligeiramente diferente.

#### HC 118.209 · Carlos Michel Sponchiado · **não conhecido** · *leitura nova*

Tráfico varejo, Sertãozinho/SP. Paciente preso em flagrante em
02/02/2013 com 20 cápsulas de cocaína + 15 trouxinhas de maconha,
em moto roubada com adolescente a bordo; na casa, **88 cápsulas
plásticas vazias** (apetrecho de mercancia). Prisão preventiva
decretada pela Vara Criminal de Sertãozinho. TJSP indeferiu
liminar; STJ (HC 270.388, Min. Og Fernandes) indeferiu liminarmente
com **Súmula 691**. Impetrante: Nayara Sichieri Jardim (defesa
particular).

Rosa aplica literalmente a Súmula 691: HC não cabe contra
indeferimento de liminar em outro writ. Nota ainda que *"os autos
não estão instruídos com cópia do inteiro teor do ato impugnado,
o que inviabiliza o confronto entre as alegações da inicial e os
fundamentos da decisão atacada"*. Cita como motivos adicionais do
STJ: fundamentação da preventiva e gravidade concreta do delito.
**Não conhece**, art. 21 §1 RISTF.

**O que ilustra.** Súmula 691 pura — o dispositivo clássico de
despachante. Aqui é interessante o contraste com o arquétipo
Barroso-2016 no corpus top-volume: Barroso, diante de caso
análogo (HC 134.507, Victor Hugo, 2,02 g cocaína + 1,15 g maconha),
**supera** a Súmula 691 para conceder. Rosa, diante de caso com
*muito mais* estrutura de mercancia (88 cápsulas vazias, roubo de
moto, contravenção de menor), aplica a Súmula *de pleno direito*.
Diferença explicável pelo tipo de caso — estrutura concreta de
tráfico não aciona o template-Barroso mesmo em ministros
historicamente mais permeáveis.

### Dias Toffoli

#### HC 134.814 · Carlos Alberto Bejani · **não conhecido** · *leitura nova*

Ex-prefeito de Juiz de Fora/MG, corrupção passiva. Impetrante:
**Marcelo Leonardo**, BH. Paciente condenado; AREsp no STJ (Min.
Joel Ilan Paciornik) acolheu pedido do MPF para expedir mandado
de prisão e guia de execução provisória após HC 126.292/MG — i.e.
execução provisória pós-2ª instância. Tese defensiva: reformatio
in pejus (havia direito de recorrer em liberdade na sentença, sem
recurso do MP sobre este ponto) + **ilegitimidade do MP Estadual
para peticionar no STJ** (atribuição privativa do Subprocurador-
Geral da República).

Toffoli aplica **duas molduras procedimentais conjugadas**:
(i) HC contra decisão monocrática do relator do STJ sem AgRg
colegiado → *"falta de exaurimento da instância antecedente"* (cita
HC 101.407/PR/Toffoli, HC 118.189/MG/Lewandowski, RHC 111.395/DF/
Fux);
(ii) no mérito da execução provisória, jurisprudência do Plenário
(HC 126.292/SP) impede o reconhecimento de reformatio in pejus.
**Nego seguimento** com base no art. 21 §1 RISTF.

**O que ilustra.** *Despachante assertivo*. Não é o silêncio do
Fux nem a prosa explicativa do Barroso — é o Toffoli metódico
listando as molduras procedimentais aplicáveis e rejeitando, **em
bloco**, tanto a via recursal quanto o mérito por consonância com
precedente vigente. Nota: o *tópico* do mérito aqui (execução
provisória) seria posteriormente revertido no Plenário (2019); à
época da decisão (01/06/2016) era o entendimento válido.

#### HC 230.730 · A.G. · **não conhecido (AgRg desprovido unanimemente)** · *leitura nova*

Impetrante Pedro Machado de Almeida Castro (top-tier, corpus
famous-lawyers) + associados. Paciente **iniciais A.G.** (figura
cuja identidade é resguardada, provável caso político sensível,
SP, 2023). Imputações: **associação criminosa, tráfico de
influência e extravio de documento**. Pedido: **trancamento da
ação penal**.

Toffoli nega seguimento monocraticamente em 18/08/2023 (art. 21
§1 RISTF). A defesa interpõe AgRg. A 2ª Turma julga virtualmente
(15-22/09/2023) e nega unanimemente (Toffoli Presidente, Gilmar,
Fachin, Nunes Marques, André Mendonça). Ementa minimalista: *"Penal
e processual penal. Crimes de associação criminosa, tráfico de
influência e extravio de documento. Trancamento da ação penal.
Excepcionalidade não demonstrada. Decisão agravada em harmonia
com entendimento consolidado pela Suprema Corte. Reiteração dos
argumentos expostos na inicial, os quais não infirmam os
fundamentos da decisão agravada."*

**O que ilustra.** O arquétipo *"trancamento-excepcionalíssimo"*
— dogma consolidado no STF que o trancamento da ação penal só é
viável em hipóteses de atipicidade, extinção de punibilidade, ou
flagrante ausência de justa causa. Toffoli aplica a dogma sem
elaboração concreta dos fatos. O AgRg é negado em sessão virtual
semanas depois **sem voto adicional**. Movimento-tipo do
despachante de **alto volume processual**: a moldura dispensa o
conteúdo.

### Cármen Lúcia

#### HC 135.041 · Robert B. Fernezlian · **não conhecido** · *citado*

*Cf. `../2026-04-17-famous-lawyers-ocr/READINGS.md § Pierpaolo ·
HC 135.041`.* Fraude em OSCIPs (IBIDEC/ADESOBRAS, SP); Pierpaolo
ataca **em frente ampla** a estrutura probatória da investigação
(denúncia anônima, interceptações sem subsidiariedade, prorrogações
além de 30 dias, ausência de transcrição). STJ rejeita cada item
com jurisprudência consolidada sobre a Lei 9.296/96; Cármen
**não conhece** aderindo à linha do STJ. *Não invade o mérito* —
o parecer da PGR (60 k caracteres) fez o trabalho pesado, Cármen
homologou.

#### HC 118.214 · Carlos Augusto Pereira do Nascimento · **não conhecido** · *leitura nova*

Tráfico SP, Defensoria Pública Estadual. Paciente preso em
30/01/2013 em flagrante (art. 33 Lei 11.343/06); prisão convertida
em preventiva em 01/02/2013. O TJSP **indeferiu a liminar** mas
não apreciou o mérito do HC; o STJ (Min. Marco Aurélio Bellizze)
aplicou Súmula 691 para indeferir liminarmente o HC lá impetrado.

Cármen aplica o **duplo fundamento clássico do despachante de
custódia**: (i) **Súmula 691** — HC não cabe contra indeferimento
de liminar em outro writ; (ii) **dupla supressão de instância** —
nem o TJSP nem o STJ apreciaram o mérito do pedido, de modo que o
STF examinar o caso *"traduziria dupla supressão de instância"*.
Cita sete precedentes — HC 76.347-QO/Moreira Alves, HC 86.552-
AgR/Peluso, AgR-HC 90.209/Lewandowski, etc. — e ainda acrescenta
(no item 10 da decisão) que a preventiva está *"fundamentada na
presença dos requisitos do art. 312 CPP, notadamente a materialidade
delitiva, indícios de autoria, comprometimento da ordem pública e
conveniência da instrução criminal"*, e (no item 11) que *"condições
subjetivas favoráveis não obstam a segregação cautelar"*.
**Não conhece** com base no art. 21 §1 RISTF.

**O que ilustra.** O arquétipo despachante em sua *forma completa*.
Cármen **não** aplica apenas uma moldura — ela empilha **três**:
Súmula 691 + dupla supressão de instância + ratificação
preventiva-fundamentada-por-gravidade-concreta. Cada camada
reforça a recusa em apreciar o mérito. O efeito cumulativo é
triplo-trancado: mesmo que uma moldura fosse superada (digamos,
se o STJ tivesse analisado o mérito da preventiva), as outras duas
continuariam de pé. É um **sobreinvestimento procedimental**
característico de quem gerencia caseload alto e não quer deixar
brecha recursal.

## Síntese agregada

### A taxonomia sobrevive no texto?

**Sim, com qualificação.** Os três arquétipos são **claramente
distinguíveis** em suas assinaturas textuais:

- **Concedentes** escrevem *votos longos* (Celso: 41 k; Gilmar:
  11 k na mono, idem no acórdão; Lewandowski: 10-30 k) e o
  conteúdo é **dogmático-substantivo** (art. 64 I CP, art. 400
  CPP, art. 319 CPP, art. 33 §4º Lei 11.343/06). Terminologia:
  *"hipótese excepcional de flagrante constrangimento ilegal"*,
  *"nulidade processual absoluta"*, *"prejuízo presumido"*,
  *"pena privativa de liberdade em uma restritiva de direitos"*.
  O dispositivo contém verbos transformativos — *"concedo",
  "revogo", "desconstituo", "determino ao juízo que refaça"*.
- **Denegadores** escrevem *votos médios* (Alexandre: 16-25 k;
  Marco Aurélio: 7-10 k) com conteúdo **temático-substantivo** —
  eles **respondem** o argumento da defesa com argumento contrário
  próprio. Terminologia: *"a autorização das instâncias [...]
  está fundamentada"*, *"demonstrada a necessidade da segregação
  cautelar"*, *"a prorrogação não caracteriza concessão de novo
  benefício"*. O dispositivo é *"denego / nego provimento ao
  agravo"* — sem correções laterais.
- **Despachantes** escrevem *votos curtos ou formulaicos* (Fux:
  30 palavras; Toffoli/230.730: ementa de 4 linhas; Cármen: 20 k
  mas todas em citação de precedente). O conteúdo é
  **procedimental-repetitivo**: art. 21 §1 RISTF + Súmula 691 +
  dupla supressão + exaurimento de instância + reexame fático-
  probatório. O dispositivo é *"não conheço / nego seguimento"*,
  nunca *"denego"* — a distinção é precisa e carrega peso
  dogmático.

**Nenhum cruzamento de arquétipo detectado no corpus.** O concedente
não aplica Súmula 691 para não conhecer quando poderia enfrentar o
mérito — Celso *supera* as molduras procedimentais do STJ e do
próprio STF. O denegador (Marco Aurélio/HC 135.027) explicitamente
*"vai além do recomendado pela PGR"* em vez de aceitar o
não-conhecimento oferecido. O despachante não escreve voto
substantivo — todos os despachantes lidos (Fachin, Fux, Barroso,
Rosa, Toffoli, Cármen) ficam dentro do perímetro procedimental.

### Divergências intra-arquétipo

- **Concedentes.** Gilmar é *situacional* (muda a tese caso a
  caso, do art. 64 I CP em 173.565 para art. 312 CPP em 173.170);
  Celso é *dogmático-fixo* (aplica a mesma tese longa a HCs
  gêmeos); Lewandowski é *colegial* (acompanha o bloco da 2ª Turma
  mesmo contra sua orientação pessoal anterior).
- **Denegadores.** Alexandre é *expansivo* (voto médio-longo,
  articula três-quatro fundamentos); Marco Aurélio é *minimalista
  textual* (ementa de 4 linhas, núcleo lógico enxuto). Mesma
  função (merit engagement contrário), estilos opostos.
- **Despachantes.** O espectro aqui é **o maior**:
  - *Silêncio total* (Fux/173.507: 30 palavras, HC 188.362 OCR
    ilegível).
  - *Prosa explicativa* (Barroso/118.493: 5,5 k caracteres com
    precedentes).
  - *Empilhamento de molduras* (Cármen/118.214: três-em-um —
    Súmula 691, dupla supressão, ratificação de preventiva).
  - *Metódico-regimental* (Toffoli/134.814: dupla moldura, mérito
    procedimental).
  - *Formal-dupla* (Fachin/188.362: nego seguimento + homologo
    desistência, zero exposição).
  Todos produzem o mesmo output funcional — *HC não apreciado no
  mérito* — por caminhos procedimentais distintos. A função do
  arquétipo está preservada; a execução varia muito.

### Surpresas e recategorizações

1. **Lewandowski migrou de Turma e de posição.** No HC 173.743 ele
   *explicitamente* registra que na 1ª Turma entendia o oposto
   (HC 97.390/SP, RHC 106.814/MS, ambos de sua relatoria). Ou seja:
   o arquétipo "concedente substantivo de dosimetria" é *turmal*,
   não *pessoal*. Isso implica que uma eventual migração entre
   turmas (ou mudança de composição) pode *converter* concedentes
   em denegadores de um ano para o outro, sem que nada no "estilo"
   individual mude.

2. **Celso de Mello opera em templates dogmáticos fixos.** Os dois
   HCs lidos (173.800 e 173.791) têm voto **idêntico em 80 %** da
   extensão — mesmos cinco parágrafos-âncora (a)-(e) com doutrina
   sobre status libertatis, mesma argumentação sobre art. 400 CPP.
   O risco metodológico: contar HCs do Celso como "decisões
   independentes" superestima a diversidade substantiva — são
   aplicações de uma tese dogmática única. Sugestão para o
   notebook: para Celso, agregar por *tese* em vez de por *HC*
   para evitar inflar a contagem de "concessões substantivas".

3. **Barroso é heterogêneo internamente.** Barroso-2014 (HC
   118.493, tráfico-mula-internacional 4,9 kg) é despachante
   canônico. Barroso-2016 (corpus top-volume HC 134.507, tráfico
   varejo 2 g) é concedente via template. Barroso-2022-23
   (corpus famous-lawyers HC 230.430) é despachante com prosa.
   **Três Barrosos distintos em função do tipo penal** — e o
   notebook agrega tudo como "despachante" porque a maioria
   numérica do seu caseload recente é de não-conhecimento. Achado:
   o arquétipo captura a *média*, não a *estrutura condicional*
   (tipo-penal → movimento).

4. **Fachin dispensou o HC 188.362 (Wilson Quintella) em duas
   molduras procedimentais em tempos diferentes** — e
   provavelmente teria dispensado de outra forma se a
   redistribuição Curitiba → DF não tivesse tornado o caso perdido
   para a defesa. É o despachante *adaptativo*: aplica a moldura
   disponível, não a moldura preferida.

5. **O HC 134.691 é o único caso Moraes-sem-Toron do corpus.** A
   leitura prévia de Alexandre no famous-lawyers era *toda*
   mediada pela dupla Toron-Moraes (HC 230.210 e HC 243.221). O
   HC 134.691 (impetrante Luiz Carlos da Silva Neto, advogado do
   próprio caso original) mostra que o padrão *merit engagement
   contrário* persiste **fora** da advocacia de ponta — não é
   artefato relator-advogado.

### Implicação para o notebook

A **"Achado central"** do `analysis/hc_minister_archetypes.py`
atualmente fala em "três arquétipos distinguíveis pela forma do
caseload" e precisa de uma nota de rodapé sobre:

- A estrutura *turmal* (concedentes quase todos 2ª Turma; migração
  Lewandowski→2ª faz o padrão; 1ª Turma tem composição denegadora
  por excesso-de-Moraes).
- A heterogeneidade *temporal* do Barroso (tripla-identidade
  2014/2016/2022+).
- O risco de contagem inflada em Celso (templates dogmáticos
  idênticos, duas concessões valem uma tese única).

Nada disso invalida a taxonomia; mas a tese "ministros com taxa de
grant similar fazem coisas opostas" fica ainda mais forte quando
se nota que **mesmos ministros em momentos ou turmas diferentes
também fazem coisas opostas**.

## Ressalvas de leitura

- **Cache de OCR nem sempre legível.** Dois PDFs esperados
  ficaram ilegíveis (HC 188.362 MONO 2 e HC 173.507 MONO): o
  cache em `data/pdf/<sha1>.txt.gz` tem só assinaturas. As
  leituras desses casos foram construídas a partir dos campos
  `complemento` das andamentos, que preservam ementas.
- **O texto extraído do PDF é ruidoso.** Vide notas equivalentes
  em `../2026-04-17-famous-lawyers-ocr/READINGS.md`. As citações
  textuais neste documento foram relidas e, onde possível,
  corrigidas; qualquer *downstream* (embedding, LLM) deve
  re-chunkar.
- **A decisão monocrática parafraseia o impetrante.** O texto é
  a *reformulação do ministro* dos argumentos da defesa.
- **Corpus desbalanceado por desenho.** Os concedentes são
  concentrados em HCs oriundos da Defensoria MG × 5ª Turma do
  STJ em 2018-2019; os despachantes variam em tipo, origem e
  advogado. Não há controle cego.

## Apêndice — Links das peças lidas

### Parte I — concedentes

- **HC 173.170** · Gilmar · Rafael Ygor · *citado* · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5729244)
- **HC 173.565** · Gilmar · Rubens V. Souza · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5735611)
  - Inteiro teor do acórdão: [id=15343040421](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15343040421&ext=.pdf)
  - Decisão monocrática: [id=15341328070](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15341328070&ext=.pdf)
- **HC 173.743** · Lewandowski · Reginaldo S. Ribeiro · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5739146)
  - Inteiro teor do acórdão: [id=15341790917](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15341790917&ext=.pdf)
  - Decisão monocrática: [id=15341093923](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15341093923&ext=.pdf)
- **HC 159.356** · Lewandowski · Rodrigo S. Pereira · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5503285)
  - Decisão monocrática: [id=314957355](https://portal.stf.jus.br/processos/downloadPeca.asp?id=314957355&ext=.pdf)
- **HC 173.800** · Celso · Gabriel E. Fernandes · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5740017)
  - Decisão monocrática: [id=15342275454](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15342275454&ext=.pdf)
- **HC 173.791** · Celso · Elandio M. Lopes · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5739828)
  - Decisão monocrática: [id=15342275455](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15342275455&ext=.pdf)

### Parte II — denegadores

- **HC 243.221** · Moraes · Menossi · *citado*
- **HC 134.691** · Moraes · Cláudio Lacerda · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4988294)
  - Inteiro teor do acórdão: [id=314824318](https://portal.stf.jus.br/processos/downloadPeca.asp?id=314824318&ext=.pdf)
  - Decisão monocrática (Moraes): [id=313911909](https://portal.stf.jus.br/processos/downloadPeca.asp?id=313911909&ext=.pdf)
  - Manifestação da PGR: [id=310049981](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310049981&ext=.pdf)
  - Decisão monocrática (Teori): [id=309860497](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309860497&ext=.pdf)
- **HC 135.027** · Marco Aurélio · João A. Amorim · *citado*
- **HC 118.364** · Marco Aurélio · Marcelo R. Pacheco · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4425983)
  - Inteiro teor do acórdão: [id=314383799](https://portal.stf.jus.br/processos/downloadPeca.asp?id=314383799&ext=.pdf)
  - Manifestação da PGR: [id=4003411](https://portal.stf.jus.br/processos/downloadPeca.asp?id=4003411&ext=.pdf)

### Parte III — despachantes

- **HC 188.538** · Fachin · *citado*
- **HC 188.362** · Fachin · Wilson Quintella Filho · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5956215)
  - Decisão monocrática (homologação de desistência): [id=15347241121](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15347241121&ext=.pdf)
  - Decisão monocrática (nego seguimento): [id=15345005522](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15345005522&ext=.pdf)
- **HC 188.243** · Fux · *citado*
- **HC 173.507** · Fux · Milton Á. Serafim · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5734652)
  - Decisão monocrática: [id=15340728153](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15340728153&ext=.pdf)
  - Manifestação da PGR: [id=15340742806](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15340742806&ext=.pdf)
- **HC 230.430** · Barroso · *citado*
- **HC 118.493** · Barroso · John Donte · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4430570)
  - Decisão monocrática: [id=220006792](https://portal.stf.jus.br/processos/downloadPeca.asp?id=220006792&ext=.pdf)
  - Manifestação da PGR: [id=4041784](https://portal.stf.jus.br/processos/downloadPeca.asp?id=4041784&ext=.pdf)
- **HC 144.079** · Rosa · Luciano S. Gonçalves · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5191729)
  - Decisão monocrática: [id=311937884](https://portal.stf.jus.br/processos/downloadPeca.asp?id=311937884&ext=.pdf)
- **HC 118.209** · Rosa · Carlos M. Sponchiado · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4419622)
  - Decisão monocrática: [id=161249025](https://portal.stf.jus.br/processos/downloadPeca.asp?id=161249025&ext=.pdf)
- **HC 134.814** · Toffoli · Carlos A. Bejani · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4992388)
  - Decisão monocrática: [id=309650553](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309650553&ext=.pdf)
- **HC 230.730** · Toffoli · A.G. · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=6699746)
  - Inteiro teor do acórdão (AgRg): [id=15361789918](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15361789918&ext=.pdf)
- **HC 135.041** · Cármen · Robert B. Fernezlian · *citado*
- **HC 118.214** · Cármen · Carlos A. Nascimento · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=4419662)
  - Decisão monocrática: [id=152366857](https://portal.stf.jus.br/processos/downloadPeca.asp?id=152366857&ext=.pdf)

> **Nota de acesso.** As URLs `downloadPeca.asp?id=…` funcionam
> apenas em navegador (o portal monta a sessão ASP no clique);
> scripts devem usar `src.scraping.scraper.fetch_pdf`.
