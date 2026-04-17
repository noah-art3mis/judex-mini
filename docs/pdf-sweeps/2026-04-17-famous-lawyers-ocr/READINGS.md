# Famous-lawyer HC — leituras substantivas pós-OCR

Companion analítico do `SUMMARY.md` (que cobre o lado de engenharia:
55 candidatos, 34 recuperados, 6.6× ganho de texto, 2 falhas
transientes de WAF). Este documento registra **o que os textos
efetivamente dizem** — as leituras caso-a-caso das decisões
monocráticas / acórdãos / manifestações da PGR lidos antes e depois
da passagem de OCR, e o impacto do novo material no diagnóstico do
corpus "advocacia de ponta × HC".

Este conteúdo foi retirado do notebook `analysis/hc_famous_lawyers.py`
na simplificação de 2026-04-17 (o notebook ficou restrito ao achado
executivo + tabela-mãe de desfechos + três clusters); o registro
caso-a-caso vive aqui.

## Sumário do corpus textual

- **35 HCs** com um dos 12 nomes curados (Toron, Pierpaolo, Pedro
  Machado, Arruda Botelho, Marcelo Leonardo, Nilo Batista, Vilardi,
  Podval, Mudrovitsch, Badaró, Daniel Gerber, Tracy Reinaldet).
- **108 PDFs substantivos** (decisão monocrática / acórdão / PGR /
  despacho) em `.cache/pdf/<sha1(url)>.txt.gz`.
- **Antes do OCR:** 30/108 plenamente extraíveis por `pypdf`;
  leitura substantiva possível em 17/35 HCs.
- **Após OCR (2026-04-17):** 57/78 do subconjunto substantivo
  (~73 %) legíveis; ganho concentrado em monocráticas e acórdãos
  previamente apenas-imagem. Números de engenharia completos em
  `SUMMARY.md`.

Toron (11 HCs brutos, 10 efetivos) e Pierpaolo (6 HCs) reúnem 58
dos 108 PDFs — o recorte onde as leituras têm N útil.

## Parte I — Leituras legíveis antes do OCR

### Toron · HC 135.027 · João A. K. Amorim · Marco Aurélio · **denegado**
*Manifestação da PGR, 53 k caracteres.*

**Operação Lama Asfáltica** (MS, 2016). A PGR descreve o paciente
como *"coordenador de um suposto esquema de pagamento de propina a
agentes públicos estaduais, mediante a celebração e execução
fraudulenta de contratos administrativos subvencionados com recursos
públicos federais"*, valendo-se de *"amizade íntima com Edson Giroto
e André Puccinelli para a realização do desvio de recursos
públicos."* Imputações: peculato, corrupção ativa/passiva, fraudes a
licitações, crimes contra o SFN, lavagem de dinheiro.

**Trajetória:** preventiva em 1º grau → HC no TRF3 (liminar
indeferida, Des. Paulo Fontes) → HC no STJ (HC 359.280, Min. Maria
Thereza, indeferido liminarmente com base na **Súmula 691**) → AgRg
na 6ª Turma desprovido → HC no STF como substitutivo.

**Ataques de Toron** (ortodoxia de defesa *white-collar*): (i)
ausência de fundamentação idônea para a preventiva — inexistência
de risco de fuga (*"todas as vezes que o paciente foi preso, a
autoridade policial o encontrou em sua residência"*); (ii) falta de
contemporaneidade — os fatos do Relatório IPEI CG201507 são
anteriores à deflagração policial; (iii) ordem econômica já tutelada
pelo sequestro patrimonial; (iv) cabimento de cautelares alternativas
do art. 319 do CPP.

**Parecer da PGR:** não-conhecimento por perda superveniente de
objeto e por **supressão de instância** — o STJ nunca apreciou o
mérito por causa da Súmula 691. Marco Aurélio foi além do recomendado
e **denegou** no mérito.

### Toron · HC 139.182 · Newton Araujo · Gilmar Mendes · **não-provido**
*Manifestação da PGR, 7 k caracteres.*

**Operação Zinabre** (SP, 2017). Auditores fiscais da SEFAZ-SP, um
dos 12 corréus, denunciados com base no art. 3º, II, da Lei
8.137/1990 e art. 288 do CP. A denúncia sustenta que os auditores
*"abandonaram esse plano de trabalho fiscal e deixaram de
constituir … os créditos tributários"*, extorquindo **mais de R$ 16
milhões** da Prysmian Energia Cabos e Sistemas.

**Ataque de Toron:** **incompetência territorial** — nenhum ato
ilícito teria se consumado em Sorocaba. TJSP, STJ (5ª Turma, RHC
72.433, unânime) e PGR rejeitam: Sorocaba é **juízo prevento** (art.
75, § único, c/c art. 83, CPP), por ter sido o primeiro a atuar
cautelarmente, e a Prysmian tem unidade na cidade.

**Parecer da PGR:** *"dissentir das razões … demanda minucioso
exame fático-probatório, o que não se admite na via estreita do
habeas corpus"*. Parecer pela denegação.

### Pierpaolo · HC 135.041 · Robert B. Fernezlian · Cármen Lúcia · **não-conhecido**
*Manifestação da PGR, 45 k caracteres.*

Fraude em OSCIPs (IBIDEC / ADESOBRAS, SP, 2015). A ementa do acórdão
do STJ reproduz um **ataque em frente ampla** à espinha dorsal
probatória da investigação:

1. **Denúncia anônima** — defesa alega início a partir de anônimo.
   STJ: origem identificada (IDDEHA), e a PF fez diligências
   preliminares.
2. **Ausência de indícios prévios para a interceptação** (art. 2º, I,
   Lei 9.296) — STJ: indícios já constavam dos requerimentos
   policiais, decisão fundamentada.
3. **Subsidiariedade violada** (art. 2º, II, Lei 9.296) — STJ inverte
   o ônus: cabe à defesa demonstrar meios alternativos.
4. **Prorrogações sucessivas além de 30 dias** — STJ: *"não há
   qualquer restrição ao número de prorrogações possíveis"*, desde
   que fundamentadas.
5. **Ausência de relatório nos autos** — juntada extemporânea, sem
   prejuízo, áudios disponibilizados.
6. **Falta de transcrição integral dos diálogos** — formalidade
   desnecessária, conforme entendimento predominante.

Todos os ataques rejeitados. **Parecer da PGR:** não-conhecimento
por fático-probatório. Cármen Lúcia não conheceu.

O documento funciona como um **inventário das respostas
jurisprudenciais consolidadas do STJ à Lei 9.296/1996** — material
pronto para recortar em artigo doutrinário.

### Pierpaolo · HC 217.011 · Domingos I. Brazão · Nunes Marques · **não-conhecido**
*Decisão monocrática, 7,7 k caracteres.*

Conselheiro do TCE-RJ investigado por **organização criminosa,
corrupção passiva e lavagem de capitais** (Operação Catedral). O
acórdão do STJ descreve o arcabouço acusatório: *"os fatos
apresentados pelo MPF estão lastreados por inúmeros documentos,
coletados em diversas medidas cautelares, cabendo citar, nos seus
mais de 40 apensos, … medidas de busca e apreensão, quebras de
sigilo bancário, telemático e telefônico"* — além de depoimentos de
executivos de Andrade Gutierrez, Carioca Engenharia e Odebrecht e
das delações de Jonas Lopes de Carvalho Jr. (ex-presidente do
TCE-RJ) e filho.

**Ataque pontual de Pierpaolo:** *"ilegalidade do recebimento de
denúncia com lastro probatório apenas na palavra do delator"*.

**Nunes Marques** rejeita com o movimento padrão em dois tempos: (i)
o trancamento só é viável em atipicidade, extinção de punibilidade
ou **evidente** ausência de justa causa (HC 186.154 AgR / HC
187.227 AgR / HC 191.216 AgR); (ii) o acórdão do STJ já apontou
*"sólidos elementos de autoria e materialidade"*, de modo que
acolher a tese exigiria *"reexame do todo conjunto fático-probatório
… inviável para a via estreita do habeas corpus"* (HC 175.924 AgR /
HC 182.710 AgR / HC 190.845 AgR).

Nega seguimento com base no art. 21, § 1º, do RISTF.

## Parte II — Releituras desbloqueadas pelo OCR (2026-04-17)

Os 7 PDFs que o extrator de texto não conseguia ler antes do OCR.
Estas leituras mudam materialmente o diagnóstico do corpus,
especialmente a leitura das "três vitórias" e um caso que se revela
*não-caso*.

### Toron · HC 138.862 · Germano Jacome Patriota · Barroso · **concedido (vitória atípica)**
*Decisão monocrática, 11,6 k caracteres. Dezembro/2016.*

Prefeito municipal condenado por **homicídio na direção de veículo**
com dolo eventual (art. 121 caput CP). Pena final, após o STJ
reduzir a condenação e reconhecer a confissão espontânea de ofício:
**6 anos de reclusão**, mas em regime inicial fechado, mantido pela
6ª Turma com base em "circunstância judicial desfavorável
(consequências do crime)".

**Ataque de Toron:** ofensa à **Súmula 719/STF** — *"a imposição do
regime de cumprimento mais severo do que a pena aplicada permitir
exige motivação idônea"*.

**Barroso concede monocraticamente** (art. 192 RISTF): pena de 6
anos, paciente primário e de bons antecedentes, é "perfeitamente
compatível com o semiaberto" (art. 33 §2º b do CP). A circunstância
judicial apontada pelo STJ é insuficiente; invoca precedente RHC
119.963 (Luiz Fux).

**Recategorização.** Esta é a única "concessão" legível de Toron no
corpus — e **não é uma vitória defensiva clássica** (não houve
trancamento, nulidade, absolvição ou redução de pena). É uma
correção técnico-sumular de regime, direta e automática. O paciente
continuou condenado aos 6 anos; só mudou a inicial execução. **Se
recategorizado**, a taxa de vitória substantiva da advocacia de ponta
cai de 3/31 (~10 %) para **2/30 (~6,7 %)**.

### Pierpaolo · HC 173.047 · S.J.C. · Gilmar Mendes · **concedido (trancamento, 3-2)**
*Acórdão do AgRg do MPF, 2,3 k caracteres. Maio/2022 (concessão original = 2019).*

O PDF disponível é o **acórdão do agravo regimental do MPF contra a
concessão monocrática original de Gilmar**. A ementa é mínima:
*"Direito Processual Penal. Trancamento da ação penal. Ausência de
justa causa. Agravo regimental a que se nega provimento."*

**Detalhe que só o texto revela:** o AgRg foi **negado por maioria
(3-2), vencidos os Ministros André Mendonça e Edson Fachin**.
Composição da Segunda Turma: Nunes Marques (Presidente), Gilmar,
Lewandowski, Fachin, Mendonça. **A concessão sobreviveu por um
voto** — se Fachin houvesse acompanhado a divergência a concessão
teria caído 3-2 contra.

Não temos o conteúdo da monocrática original (a concessão de 2019)
— apenas o acórdão que a confirma. A teoria vencedora ("ausência de
justa causa") é descrita em alto nível, sem detalhamento fático.

### Toron · HC 216.912 · Aécio Neves · Lewandowski · **não-caso**
*Decisão monocrática, 2,8 k caracteres. Junho/2022.*

**Este HC é um artefato de autuação, não um caso litigado.** A
petição havia sido endereçada ao **TRE-MG**, não ao STF; o
Coordenador de Registros e Informações Processuais do TRE
protocolou-a por engano no STF. Lewandowski, com base no art. 21, I,
do RISTF, **cancela a distribuição** sem pronunciamento
jurisdicional: *"tendo em vista o manifesto desacerto do citado
servidor, não cabe, por corolário lógico, qualquer pronunciamento
jurisdicional desta Suprema Corte"*.

**Implicação.** O `outcome=None` / "pendente" do HC 216.912 nos
metadados induz a erro: não foi caso ativo nem caso perdido — foi
*case-never-adjudicated*. **Remoção recomendada do denominador**
"decididos" + "pendentes"; reduz o N efetivo de Toron de 11 para 10.
O caso Aécio Neves propriamente dito tramitou no TRE-MG sob outro
identificador.

### Toron · HC 230.210 · L.C.S. · Alexandre de Moraes · **denegado (unânime)**
*Acórdão do AgRg, 3,8 k caracteres. Agosto/2023 (+ EDcl rejeitados em setembro/2023).*

**Crimes sexuais contra vulneráveis** (art. 217-A CP): mestre de
caratê acusado de atos libidinosos com alunos durante viagens e
treinos (*"prevalecendo-se, em tese, da autoridade de mestre de
caratê, e aproveitando-se de situações em que tinha os alunos em sua
guarda"*). Paciente **foragido** ao tempo do julgamento.

**Ataque de Toron:** cautelares alternativas no lugar da preventiva.

**Alexandre de Moraes nega unanimemente** (Primeira Turma: Barroso
Presidente, Cármen Lúcia, Fux, Alexandre, Zanin): *"a periculosidade
do agente, evidenciada pelo modus operandi na prática do delito,
justifica a prisão preventiva para garantia da ordem pública"*
(invocando HC 95.414, Eros Grau); o fato de o paciente permanecer
fora do âmbito da Justiça reforça a preventiva também **para
garantia da aplicação da lei penal**.

Os embargos de declaração seguintes foram também rejeitados por
unanimidade em setembro/2023.

**Leitura da composição.** É uma Primeira Turma com Barroso e Cármen
Lúcia — ministros historicamente mais permeáveis a HCs concedidos
segundo `hc_minister_archetypes.py`. Aqui, diante de crimes sexuais
contra vulneráveis + fuga, a unanimidade contrária mostra que certos
perfis de caso escapam da *relator-lottery* que domina o resto do
corpus.

### Toron · HC 243.221 · Menossi · Alexandre de Moraes · **denegado (unânime)**
*Acórdão do AgRg, 4,1 k caracteres. Agosto/2024 (+ EDcl rejeitados em setembro/2024).*

**Falsidade ideológica (×20)** + **peculato (×8)** (arts. 299 par.
único e 312 caput CP). Paciente originário do Mato Grosso do Sul.

**Ataque de Toron:** nulidade de interceptação telefônica — tese
caracteristicamente *Pierpaolo-style* (ataque à estrutura
probatória), protagonizada por Toron neste caso.

**Alexandre de Moraes rejeita unanimemente** (Primeira Turma:
Alexandre Presidente, Cármen, Fux, Zanin, Flávio Dino) invocando
cláusula de reserva jurisdicional (CF art. 5º XII; Lei 9.296/96): a
decisão autorizadora estava fundamentada na representação policial +
parecer ministerial, com justificativa idônea sobre necessidade e
imprescindibilidade. Aplicam Inq. 2.424 (Peluso), HC 94.028 (Cármen),
HC 103.418 (Toffoli), HC 96.056 (Gilmar) — o pacote jurisprudencial
consolidado do STF sobre interceptações.

EDcl também unânimes na rejeição.

**Padrão Moraes-2024 confirmado.** Dois casos Toron relatados por
Alexandre de Moraes, dois anos distintos (2023 e 2024), duas
unanimidades contrárias — em ambas as sessões com Cármen e Fux
presentes. A quase-total penetração de Alexandre na 1ª Turma
criminal torna a composição atual mais homogênea contra a defesa do
que o histórico relator-a-relator sugeriria.

### Pierpaolo (+ Tamasauskas) · HC 188.395 · Luiz Carlos de Lima · Luiz Fux · **não-conhecido**
*Decisão monocrática, 19,4 k caracteres. Agosto/2020.*

**HC "pandemia"**: tentativa de furto qualificado (art. 155 §4º +
art. 14 II CP), pena de 3 anos e 4 meses em regime semiaberto,
paciente com bronquite aguda e pai de dois menores (12 anos e
recém-nascido). Pedido: **prisão domiciliar** baseado em
**Recomendação 62/2020 CNJ**, Súmula Vinculante 56, superlotação da
Penitenciária Dr. Geraldo de Andrade Vieira (São Vicente I).

**Fux não conhece por duas razões convergentes:**

1. **Ausência de exame colegiado no STJ** — a monocrática do STJ não
   foi colegiada; a CF art. 102 II "a" exige *"decidido em única
   instância pelos Tribunais Superiores, se denegatória a decisão"*.
   Cita HC 167.996-AgR (Barroso) e HC 171.492-AgR (Lewandowski).
2. **Reexame fático-probatório**: a alegação de vulnerabilidade
   individual do paciente à pandemia *"demandaria profunda valoração
   probatória"*, incompatível com o HC.

**Novo mini-cluster sugerido — HCs COVID (2020).** Faixa temporal e
temática ainda não destacada no corpus agregado. A extensão da
monocrática (~19 k caracteres vs. média denegatória de ~7 k) sugere
que o caso não era trivial para fechar, provavelmente porque a
Recomendação 62/2020 CNJ abria margem explícita a concessões
excepcionais — mas a porta procedimental (falta de colegiado) foi
suficiente para barrar o mérito.

### Pierpaolo (+ Tamasauskas) · HC 202.903 · Missawa · Rosa Weber · **pendente (só indeferimento de liminar)**
*Decisão monocrática, 8,8 k caracteres. Junho/2021.*

**Crime colegiado white-collar**: fraudes a licitação (Lei 8.666) +
formação de cartel (Lei 8.137), no contexto de licitação da
**Companhia Paulista de Trens Metropolitanos** ("320 carros" e "64
carros").

**Tese nova e interessante:** **extensão dos efeitos** da atipicidade
reconhecida pela **6ª Turma do STJ** em favor de **corréus** no
mesmo caso. Há uma assimetria interna ao STJ — a 6ª Turma reconheceu
atipicidade para alguns corréus; a 5ª Turma, não conhecendo o REsp
do paciente, manteve a persecução apenas contra ele.
Argumento-defesa: isonomia (corréus similarmente situados, mesma
denúncia).

**Rosa Weber indefere a liminar** com o padrão
*trancamento-excepcionalíssimo* (atipicidade manifesta, extinção de
punibilidade, ausência de suporte probatório mínimo) — esses
pressupostos não aparecem na delibação; pronunciamento do STJ está
fundamentado. Manda oitiva da PGR para posterior exame de mérito.

Este PDF é **indeferimento de liminar**, não decisão terminativa. O
`outcome=None` reflete o estado real: caso ainda em curso. O ângulo
tático "assimetria 5ª vs 6ª Turma do STJ" é uma das poucas teses
efetivamente novas no corpus — distinta tanto do ataque
*procedimental-sumular* (Toron / Súmula 691) quanto do ataque
*estrutura probatória* (Pierpaolo / interceptação).

## Parte III — Implicações para o diagnóstico do corpus

**Insight agregado.** O material pré-OCR já sugeria que o
"prêmio-advogado-famoso" era invisível nesse N; o pós-OCR permite
afirmar algo ligeiramente mais forte: **as vitórias continuam sendo
raras, frágeis (quando substantivas) ou técnicas (quando obtidas sem
fricção)**. Não há evidência de que o *top bar* consiga reverter
decisões de mérito no STF; o corpus testemunha só correções sumulares,
um trancamento apertado e um mérito totalmente litigado (Palocci).

Releituras das três vitórias:

| HC      | advogado  | categoria pós-OCR                                      |
|---------|-----------|--------------------------------------------------------|
| 143.333 | Tracy     | ✓ vitória defensiva plena (mantida)                    |
| 173.047 | Pierpaolo | ✓ vitória substantiva, **frágil** (3-2 no colegiado)   |
| 138.862 | Toron     | ✗ não é vitória defensiva — correção sumular de regime |

Somando a retirada do HC 216.912 (*non-case*): **N efetivo de Toron
= 10**, corpus decidível = 30, vitórias substantivas = 2 →
**~6,7 %**.

Tabela de status das releituras:

| HC      | advogado  | resultado     | relator             | leitura pós-OCR                                              |
|---------|-----------|---------------|---------------------|--------------------------------------------------------------|
| 138.862 | Toron     | concedido¹    | Barroso             | correção sumular de regime — não defensiva clássica          |
| 173.047 | Pierpaolo | concedido     | Gilmar Mendes       | trancamento mantido 3-2 no AgRg do MPF                       |
| 216.912 | Toron     | *non-case*    | Lewandowski         | autuação cancelada — erro de cartório TRE-MG                 |
| 230.210 | Toron     | denegado      | Alexandre de Moraes | crimes sexuais art. 217-A, unanimidade 1ª Turma              |
| 243.221 | Toron     | denegado      | Alexandre de Moraes | nulidade interceptação rejeitada unanimemente                |
| 188.395 | Pierpaolo | não-conhecido | Luiz Fux            | HC-COVID, barrado por falta de colegiado no STJ              |
| 202.903 | Pierpaolo | pendente      | Rosa Weber          | só indeferimento de liminar — mérito aguarda PGR             |

¹ Recategorizável como "correção de regime".

**O que o diagnóstico comparado Toron vs. Pierpaolo gana com o OCR.**

- A única vitória de Toron que o OCR tornou legível (HC 138.862,
  Patriota) **não atacou o mérito** — foi correção técnico-sumular
  de regime, garantida pela Súmula 719. Não há, no corpus, um único
  exemplo de ataque Toron-*ambulatório* (preventiva, cautelares,
  competência) que tenha alcançado mérito com resultado favorável.
- A vitória de Pierpaolo (HC 173.047, S.J.C.) foi trancamento por
  ausência de justa causa — ataque típico do escritório à estrutura
  acusatória. Mas o acórdão do AgRg do MPF, agora legível, mostra
  que **o resultado foi 3-2 no colegiado, com Fachin e André
  Mendonça pela cassação**. Sobreviveu por um voto.
- Os quatro casos Toron denegados/não-conhecidos que o OCR liberou
  (HC 216.912 não-caso, HC 230.210 crimes sexuais, HC 243.221
  interceptação, HC 188.395 COVID) confirmam o padrão: rejeição
  unânime da Primeira Turma quando o tema sai do perímetro
  "ambulatório" (prisão preventiva rotineira, dosimetria) e entra em
  crime grave (art. 217-A), nulidade probatória de interceptação,
  ou pedido domiciliar-COVID.

## Ressalvas de leitura

- **O texto extraído do PDF é ruidoso.** O modo *layout* do `pypdf`
  preserva o espaçamento mas também os artefatos da justificação em
  colunas; o OCR `hi_res` da Unstructured preserva mais texto mas
  introduz seus próprios erros de reconhecimento. Qualquer passo
  downstream de embedding / LLM deve re-chunkar, não ingerir cru.
- **A decisão monocrática parafraseia o impetrante.** O texto é a
  *reformulação do ministro* dos argumentos do advogado, não a
  petição em si. Para a petição própria seria necessário acessar os
  PDFs em `peticoes[]`, que não estão linkados na lista de andamentos
  e demandam um caminho de download à parte.
- **35/37 HCs têm ao menos um PDF substantivo em andamentos.** Dois
  HCs estão em fases iniciais (despacho só, sem peça de mérito).

## Apêndice — Links das peças exclusivas deste documento

Três HCs da Parte I são discutidos apenas aqui (não voltam à análise
executiva do notebook). Seus links ficam neste apêndice; os demais
HCs citados acima — HC 143.333, 173.047, 138.862, 216.912, 217.011,
230.210, 243.221, 188.395, 202.903 — têm links centralizados no
notebook `analysis/hc_famous_lawyers.py`, seção "Links dos HCs e das
peças substantivas".

- **HC 135.027** · Toron · Lama Asfáltica · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5001089)
  - Inteiro teor do acórdão: [id=314202957](https://portal.stf.jus.br/processos/downloadPeca.asp?id=314202957&ext=.pdf)
  - Decisão monocrática: [id=312757084](https://portal.stf.jus.br/processos/downloadPeca.asp?id=312757084&ext=.pdf)
  - Decisão monocrática: [id=312745963](https://portal.stf.jus.br/processos/downloadPeca.asp?id=312745963&ext=.pdf)
  - Manifestação da PGR: [id=312056849](https://portal.stf.jus.br/processos/downloadPeca.asp?id=312056849&ext=.pdf)
  - Manifestação da PGR: [id=310108626](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310108626&ext=.pdf)
  - Decisão monocrática: [id=309786237](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309786237&ext=.pdf)
- **HC 139.182** · Toron · Op. Zinabre · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5107650)
  - Inteiro teor do acórdão: [id=15339938695](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15339938695&ext=.pdf)
  - Decisão monocrática: [id=15339206270](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15339206270&ext=.pdf)
  - Manifestação da PGR: [id=311474573](https://portal.stf.jus.br/processos/downloadPeca.asp?id=311474573&ext=.pdf)
- **HC 135.041** · Pierpaolo · OSCIPs IBIDEC/ADESOBRAS · [detalhe](https://portal.stf.jus.br/processos/detalhe.asp?incidente=5001749)
  - Decisão monocrática: [id=15341484641](https://portal.stf.jus.br/processos/downloadPeca.asp?id=15341484641&ext=.pdf)
  - Decisão monocrática: [id=310719135](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310719135&ext=.pdf)
  - Decisão monocrática: [id=310364447](https://portal.stf.jus.br/processos/downloadPeca.asp?id=310364447&ext=.pdf)
  - Manifestação da PGR: [id=309867051](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309867051&ext=.pdf)
  - Decisão monocrática: [id=309835958](https://portal.stf.jus.br/processos/downloadPeca.asp?id=309835958&ext=.pdf)

> **Nota de acesso.** As URLs `downloadPeca.asp?id=…` funcionam em
> navegador (o portal monta a sessão ASP no clique a partir de
> `detalhe.asp`); scripts sem cookies precisam passar por
> `src.scraping.scraper.fetch_pdf`. Mesmo shape usado em
> `tests/ground_truth/*.json` (`peticoes[].link`).

## Próximos passos sugeridos

1. **Retentativa das duas falhas de WAF** (HC 158.921, HC 202.903)
   com `--throttle-sleep 5.0` após cooldown — ver `SUMMARY.md §
   Failures`.
2. **Passagem nos 19 `unchanged`** — conferir quais são "genuinely
   short orders" (despachos de expediente, etc.) vs. casos que
   merecem retry com `strategy=ocr_only` em vez de `hi_res`.
3. **Regeneração do gap-de-corpus.** As frases "30/108 readable,
   78 image-only scans, 17/35 HCs substantivamente legíveis" —
   citadas em docs antigas do projeto — não refletem mais a
   realidade em disco. Se algum doc descritivo for regenerado, o
   ponto de partida deve ser "57/78 (~73 %) legíveis" + contagem
   fresca de HCs com pelo menos um doc substantivo ≥ 5 k chars.
