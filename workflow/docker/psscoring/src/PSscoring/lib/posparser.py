import re
import numpy as np
import pandas as pd
import gffutils
import pysam

############ Functions for analysis ############
def classifying_canonical(df: pd.DataFrame) -> pd.DataFrame:
    # IntronDist: -2, -1, 1, 2 → Canonical
    df['is_Canonical'] = np.where(df['IntronDist'].isin([-2, -1, 1, 2]), "Yes", "No")

    return df
    
def _extract_affected_region(pos: int, ref: str, alt: str) -> dict:
    """
    Function to extract the POS of the affected region by the variant
    """
    ref_len: int = len(ref)
    alt_len: int = len(alt)
    
    # Calculate the affected region
    if ref_len > alt_len:
        # Deletion
        affected_start: int = pos
        affected_end: int = pos + ref_len - 1
    elif alt_len > ref_len:
        # Insertion
        affected_start: int = pos
        affected_end: int = pos
    else:
        # Substitution
        affected_start: int = pos
        affected_end: int = pos + ref_len - 1
    
    return {'Affected_start_pos': affected_start,
            'Affected_end_pos': affected_end}

def signed_distance_to_exon_boundary(
        row, db: gffutils.FeatureDB, db_intron: gffutils.FeatureDB) -> int:
    """
    Calculate the signed distance from the nearest exon-intron boundary 
    in the intron variants.

    Parameters:
    variant_position: int, 
    db_intron: gffutils.FeatureDB
    strand: "+" or "-"

    Returns:
    A signed distance from affected region to the nearest exon-intron boundary
    """
    # Check intron variant or not
    for exon in db.children(id=row['ENST_Full'], featuretype='exon'):
        if exon.start <= int(row['POS']) <= exon.end:
            return np.nan # If an exonic variant, return NaN

    # Extract parameters
    query_enst = row['ENST_Full']
    strand = row['Strand']
    variant_position, ref, alt = int(row['POS']), row['REF'], row['ALT']

    # Check ENST availability (wheher query_enst starts with "ENST")
    if not query_enst.startswith('ENST'):
        return "[Warning] Invalid ENST ID"
        
    introns = list(db_intron.children(id=query_enst, featuretype='intron'))
    introns.sort(key=lambda intron: intron.start)

    boundaries = []
    for intron in introns:
        intron_start = intron.start
        intron_end = intron.end
        
        # Case of plus strand: 3' end (exon end position) → minus, 5' end (exon start position) → plus
        if strand == '+':
            boundaries.append((intron_start - 1, '+'))  # 5'-prime end: plus sign
            boundaries.append((intron_end + 1, '-'))    # 3'-prime end: minus sign

        # Case of minus strand: 3' end (exon start position) → minus, 5' end (exon end position) → plus
        elif strand == '-':
            boundaries.append((intron_start - 1, '-'))  # 3'-prime end: minus sign
            boundaries.append((intron_end + 1, '+'))    # 5'-prime end: plus sign
        else:
            raise ValueError("Strand must be '+' or '-'")

    # Calculate the affected region
    affected_region: dict = _extract_affected_region(variant_position, ref, alt)

    # Find the closest boundary
    closest_distance_s, closest_distance_e = None, None
    closest_sign_s, closest_sign_e = None, None

    for boundary, sign in boundaries:
        distance = abs(affected_region['Affected_start_pos'] - boundary)
        if closest_distance_s is None or distance < closest_distance_s:
            closest_distance_s = distance
            closest_sign_s = sign
        
        distance = abs(affected_region['Affected_end_pos'] - boundary)
        if closest_distance_e is None or distance < closest_distance_e:
            closest_distance_e = distance
            closest_sign_e = sign

    # Select the closest boundary 
    try:
        abs(closest_distance_s) < abs(closest_distance_e)
    except TypeError:
        print(boundaries)

    if abs(closest_distance_s) < abs(closest_distance_e):
        closest_distance, closest_sign = closest_distance_s, closest_sign_s
    else:
        closest_distance, closest_sign = closest_distance_e, closest_sign_e

    # Return the signed distance
    if closest_sign == '+':
        return int(closest_distance)
    else:
        return int(-closest_distance)

############ Functions for apply method ############
def calc_exon_loc(row, 
                  tabixfile: pysam.pysam.libctabix.TabixFile, 
                  enstcolname: str):
    """Calculate exon location from start of exon or end of exon.
    Returns:
        str: "Upstream distance : Downstream distance"
    """
    query_chr: str = f"chr{row['CHROM']}"
    query_pos: int = int(row['POS'])
    query_start: int = int(query_pos) - 1
    query_end: int = int(query_pos)
    query_enst: int = row[enstcolname]

    if row['Ex_or_Int'] == "[Warning] Invalid ENST ID":
        return '[Warning] Invalid ENST ID:[Warning] Invalid ENST ID'
    if row['Ex_or_Int'] == "Intronic":
        return 'Intronic:Intronic'

    for r in tabixfile.fetch(query_chr, query_start, query_end, 
                            parser=pysam.asGFF3()):
        
        try:
            enst = re.match(r'ENST\d+', r.transcript_id).group()
        except KeyError:
            pass
        else:
            if enst == query_enst:
                if r.feature == 'exon':
                    if r.strand == '+':
                        downd = r.end - query_pos + 1 
                        upd = query_pos - r.start
                    elif r.strand == '-':
                        downd = query_pos - r.start
                        upd = r.end - query_pos + 1
                    else:
                        return 'unk_strand'
                    return f'{upd}:{downd}'
                else:
                    pass
            else:
                pass
            
    return '[Warning] ENST_unmatch:[Warning] ENST_unmatch'

def extract_splicing_region(row) -> str:

    if row['ENST_Full'] == '[Warning] ENST_with_Ver_not_available':
        return '[Warning] Invalid ENST ID'
    if row['ex_up_dist'] == '[Warning] Invalid ENST ID':
        return '[Warning] Invalid ENST ID'
    if row['ex_up_dist'] == 'Intronic':
        return 'Intronic'
    if row['ex_up_dist'] == '[Warning] ENST_unmatch':
        return '[Warning] ENST_unmatch'

    else: 
        # if int(row['ex_down_dist']) == 0:
        if int(row['ex_up_dist']) == 1:
            return 'ex_acceptor_site'
            # return 'ex_donor_site'
        # elif int(row['ex_up_dist']) <= 2:
        elif int(row['ex_down_dist']) <= 3:
            return 'ex_donor_site'
            # return 'ex_acceptor_site'
        else:
            return 'non_SplicingExonPos'

# def extract_splai_result(row):
#     for i in range(9):  
#         info: str = row[i]
#         if info:
#             info: str = info[2:]
#             gene: str = re.match(r'[^|]+', info).group()
#             if row['gene'] == gene:
#                 return info
#             else:
#                 pass
#         else:
#             pass
#     return '[Warning] No_SpliceAI_predictions'


# def extract_splai_result_2(row, genecol: str):
#     if row['is_Multi']:
#         for i in range(17):
#             info = row[i]
#             try:
#                 info: str = re.sub(r'\w+\|', '', info, 1)
#             except:
#                 pass
#             else:
#                 gene: str = re.match(r'[^|]+', info).group()
#                 if row[genecol] == gene:
#                     return info
#                 else:
#                     pass
#     else:
#         try:
#             info: str = re.sub(r'\w+\|', '', row[0], 1)
#         except:
#             return '[Warning] No_SpliceAI_predictions'
#         else:
#             return info

def fetch_enst_full(row, db: gffutils.interface.FeatureDB):
    query_region = (f"chr{row['CHROM']}", int(row['POS']) - 1, int(row['POS']))
    for t in db.region(region=query_region, featuretype='transcript'):
        if t.id.startswith(row['ENST']):
            return t.id
        else:
            pass
    return '[Warning] ENST_with_Ver_not_available'


def calc_ex_int_num(
    row, db: gffutils.interface.FeatureDB, db_intron: gffutils.interface.FeatureDB):
    # print(f'{row["ENST_Full"]}-{row["gene"]}:{row["variant_id"]}:{row["IntronDist"]}')
    if (row['SpliceType'] == 'Donor_int' 
        or row['SpliceType'] == 'Acceptor_int'):

        introns = db_intron.children(row['ENST_Full'], featuretype='intron')
        max_intron = 0
        intron_num = 0
        while 1:
            try:
                intron = next(introns)
            except StopIteration:
                break
            else:
                max_intron += 1
                if (intron.start <= int(row['POS']) and int(row['POS']) <= intron.end):
                    intron_num = intron.attributes['exon_number'][0]
                else:
                    pass
        return f'{intron_num}/{max_intron}'
            
    elif (row['SpliceType'] == 'Donor_ex' 
          or row['SpliceType'] == 'Acceptor_ex'):
        
        exons = db.children(row['ENST_Full'], featuretype='exon')
        max_exon = 0
        exon_num = 0
        while 1:
            try:
                exon = next(exons)
            except StopIteration:
                break
            else:
                max_exon += 1
                if (exon.start <= int(row['POS']) and int(row['POS']) <= exon.end):
                    exon_num = exon.attributes['exon_number'][0]
                else:
                    pass
        return f'{exon_num}/{max_exon}'
    
    else:
        return 'unknown'
    
def select_exon_pos(row):
    try:
        # Get the minimum distance from the two distances
        if row['ex_up_dist'] and row['ex_down_dist']:
            return min(int(row['ex_up_dist']), int(row['ex_down_dist']))
        elif row['ex_up_dist']: 
            return int(row['ex_up_dist'])
        elif row['ex_down_dist']:
            return int(row['ex_down_dist'])
        else:
            return '[Warning] Unknown_SpliceType'
    except ValueError:  # if conversion to int fails
        return '[Error] Invalid_Value'


def select_donor_acceptor(row):
    """Select Donor site or Acceptor site
    Args:
        row (pd.DataFrame): Required columns are 
                            'IntronDist', 'ex_down_dist', and 'ex_up_dist'.
    Returns:
        str: 'Donor' or 'Acceptor' with 'ex' or 'int'
    """ 

    if row['IntronDist'] == '[Warning] Invalid ENST ID':
        return '[Warning] Uncalssified SpliceType'

    if isinstance(row['IntronDist'], float):  # Equal to np.nan (exonic variant)
        if row['exon_pos'] == '[Warning] ENST_unmatch':
            return '[Warning] ENST_unmatch'
        else:
            pass

        try:
            int(row['ex_down_dist'])
        except TypeError:
            return '[Warning] Unkown exon location'
        except ValueError:
            return '[Warning] Unkown exon location'
        else:               
            d = int(row['ex_down_dist'])
            u = int(row['ex_up_dist'])
            if u < d:
                return 'Acceptor_ex'
            elif u > d:
                return 'Donor_ex'
            else:
                return 'Center_of_Exon'
            
    elif int(row['IntronDist']) < 0:
        return 'Acceptor_int'
    elif int(row['IntronDist']) > 0:
        return 'Donor_int'
    else:
        return '[Warning] Uncalssified SpliceType'


def calc_prc_exon_loc(row):  
    if row['ENST_Full'] == '[Warning] ENST_with_Ver_not_available':
        return '[Warning] Invalid ENST ID'
    if row['ex_up_dist'] == '[Warning] ENST_unmatch':
        return '[Warning] ENST_unmatch'
    
    if isinstance(row['IntronDist'], float):
        try:
            curt_ex_length = int(row['ex_up_dist']) + int(row['ex_down_dist'])
        except TypeError:
            return np.nan
        
        try:
            row['Strand']
        except:
            return np.nan

        if (row['Strand'] == '+' 
                and int(row['ex_up_dist']) <= int(row['ex_down_dist'])):
            return (1- (int(row['exon_pos']) / curt_ex_length)) * 100
        
        elif (row['Strand'] == '-' 
              and int(row['ex_up_dist']) >= int(row['ex_down_dist'])):
            return (1 - (int(row['exon_pos']) / curt_ex_length)) * 100
        
        elif (row['Strand'] == '+' 
              and int(row['ex_up_dist']) > int(row['ex_down_dist'])):
            return (int(row['exon_pos']) / curt_ex_length) * 100
    
        elif (row['Strand'] == '-' 
              and int(row['ex_up_dist']) < int(row['ex_down_dist'])):
            return (int(row['exon_pos']) / curt_ex_length) * 100
    
        else:
            return '[Waring] Unexpected conditions'
    
    else:
        return 'non_exonic_variant'



