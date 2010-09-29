# Python libs
import re
import pickle
from math import log

# Third Party Libs
from dumbo import *
import nltk

# My Libs
from mycorpus import stopwords

# Program Variables
minLength = 3
maxLength = 40
maxGram = 4
upper_fraction = 0.5
separator = ','

sentence_re = r'''(?x)      # set flag to allow verbose regexps
      ([A-Z])(\.[A-Z])+\.?  # abbreviations, e.g. U.S.A.
    | \w+(-\w+)*            # words with optional internal hyphens
    | \$?\d+(\.\d+)?%?      # currency and percentages, e.g. $12.40, 82%
    | \.\.\.                # ellipsis
    | [][.,;"'?():-_`]      # these are separate tokens
'''

lemmatizer = nltk.WordNetLemmatizer()
stemmer = nltk.stem.porter.PorterStemmer()

with open('pos_tag.pkl', 'rb') as f:
    postagger = pickle.load(f)

grammar = r"""
    NBAR:
        {<NN.*|JJ>*<NN.*>}
        
    NP:
        {<NBAR>}
        {<NBAR><IN><NBAR>}
"""
chunker = nltk.RegexpParser(grammar)

def leaves(tree):
    for subtree in tree.subtrees(filter = lambda t: t.node=='NP'):
        yield subtree.leaves()

def normalise(word):
    word = word.lower()
    word = stemmer.stem_word(word)
    return word

def acceptableWord(word):
    accepted = bool(minLength <= len(word) <= maxLength
        and word.lower() not in stopwords)
    return accepted

def acceptableGram(gram):
    return bool(1 <= len(gram) <= maxGram)

def rPrecision(a, b):
    a = set(a)
    b = set(b)
    overlap = len(a.intersection(b))
    return float(overlap)/max(len(a), len(b))

# Mapper: Extracts Terms from a Document
# IN : key = (docname, line#), value = line
# OUT: (docname, term), 1
# Requires -addpath yes flag
@opt("addpath", "yes")
def termMapper( (docname, lineNum), line):
    toks = nltk.regexp_tokenize(line, sentence_re)
    toks = [ lemmatizer.lemmatize(t) for t in toks ]
    postoks = postagger.tag(toks)
    tree = chunker.parse(postoks)
    
    position = 0
    for leaf in leaves(tree):
        term = [ normalise(w) for w,t in leaf if acceptableWord(w) ]
        if not acceptableGram(t):
            continue
        payload = (lineNum is 0, position)
        yield (docname, term), (payload, 1)
        position += 1

def reducePayloads(a, b):
    return a[0] or b[0], min(a[1], b[1])

def termReducer( (docname, term), values ):
    values = list(values)
    payload = reduce(reducePayloads, [p for p,n in values])
    n = sum( [ n for p,n in values ] )
    yield (docname, term), (payload, n)

# n - term-count for the doc
# N - term-count for all docs
# payload - optional package that gets carried to the end
# IN : (docname, term), (payload, n)
# OUT: docname, (term, payload, n)
def docTermCountMapper( (docname, term), (payload, n)):
    yield docname, (term, payload, n)
    
# IN : docname, (term, payload, n)-list
# OUT: (term, docname), (payload, n, N)
def docTermCountReducer(docname, values):
    values = list(values)
    # Total count of term across all docs
    N = sum(n for (term, payload, n) in values)
    for (term, payload, n) in values:
        yield (term, docname), (payload, n, N)

# IN : (term, docname), (payload, n, N)
# OUT: term, (docname, payload, n, N, 1)
def corpusTermCountMapper( (term, docname), (payload, n, N) ):
    yield term, (docname, payload, n, N, 1)

def corpusTermCountCombiner(term, values):
    values = list(values)
    m = sum(v[-1] for v in values)
    for v in values:
        v = list(v)
        yield term, tuple(v[:-1] + [m])

# IN : term, (docname, (payload, n, N, 1)
# OUT: term, (docname, payload, n, N, 1)
def corpusTermCountReducer(term, values):
    values = list(values)
    m = sum(c for (docname, payload, n, N, c) in values)
    for (docname, payload, n, N) in (v[:4] for v in values):
        yield docname, (term, payload, n, N, m)

class FinalReducer:
    def __init__(self):
        self.doccount = float(self.params['doccount'])
    def __call__(self, docname, values):
        terms = []
        fd = nltk.probability.FreqDist()
        
        for (term, (inTitle, position), n, N, m) in values:
            #relativePos = float(position)/m
            tf = float(n)/N
            idf = log(self.doccount / m)
            tf_idf = tf * idf
            term_str = ' '.join(term)
        
            if inTitle:
                terms.append(term_str)
            else:
                score = tf_idf # * relative_pos
                fd.inc(term_str, score)
        
        # top upper_fraction of terms
        n = int(upper_fraction * len(fd))
        terms += fd.keys()[:n]
        yield docname, separator.join(terms)

def runner(job):
    job.additer(termMapper, termReducer, combiner = termReducer)
    job.additer(docTermCountMapper, docTermCountReducer)
    job.additer(corpusTermCountMapper, corpusTermCountReducer,
        combiner = corpusTermCountCombiner)
    job.additer(identitymapper, FinalReducer)

if __name__ == "__main__":
    main(runner)
