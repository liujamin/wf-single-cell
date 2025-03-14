#!/usr/bin/env python
"""Assign barcodes.

Given a whitelist of barcodes (10x or generated here?) assign raw barcodes to corrected
barcodes.
"""
import collections
from pathlib import Path

import pandas as pd
import rapidfuzz
from rapidfuzz.process import extract

from .util import wf_parser  # noqa: ABS101


def argparser():
    """Create argument parser."""
    parser = wf_parser("assign_barcodes")

    parser.add_argument(
        "--extract_barcode_tags",
        help="TSV file of read_id, uncorrected_barcode, qscores"
    )

    parser.add_argument(
        "--whitelist",
        help="File containing list of expected cell barcodes",
        type=Path
    )

    parser.add_argument(
        "--output_tags",
        help="Output TSV containing columns from `extract_barcode_tags` \
            + CB (correctred barcode) [tags.tsv]",
        type=Path
    )

    parser.add_argument(
        "--output_counts",
        help="Output TSV file containing counts for each of the assigned \
        barcodes [barcode_counts.tsv]",
        type=Path
    )

    parser.add_argument(
        "--max_ed",
        help="Max edit distance between putative barcode \
                        and the matching whitelist barcode [2]",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--min_ed_diff",
        help="Min difference in edit distance between the \
                        (1) putative barcode vs top hit and (2) putative \
                        barcode vs runner-up hit [2]",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--barcode_length",
        help="Cell barcode length [16]",
        type=int,
        default=16
    )

    return parser


def calc_ed_with_whitelist(bc_uncorr, whitelist, score_cutoff=6):
    """Find barcodes in a whilelist with the smallest edit distance.

    :param bc_uncorr: uncorrected barcode
    :param whitelist: List of possible barcodes
    :param: score_cutoff: rapidfuzz score cutoff - edit distances above this are not
        reported.
    :return:
        best matching barcode
        edit distance between best match and uncorrected barcode
        edit distance between best match and second-best natch
    """
    # result is a list of tuples (bc, ed, idx) sorted by ed.
    result = extract(
        bc_uncorr,
        whitelist,
        scorer=rapidfuzz.distance.Levenshtein.distance,
        score_cutoff=score_cutoff)

    if len(result) > 0:
        bc_match = result[0][0]
        bc_match_ed = result[0][1]
    else:
        bc_match = "X" * len(bc_uncorr)
        bc_match_ed = len(bc_uncorr)
    if len(result) > 1:
        next_match_diff = result[1][1] - bc_match_ed
    else:
        next_match_diff = len(bc_uncorr)

    return bc_match, bc_match_ed, next_match_diff


def process_records(
        extract_barcode_tags, whitelist, barcode_length, max_ed, min_ed_diff):
    """Process read tag records.

    Process read tags to assign each read a corrected cell barcode.
    Iterate over the uncorrected barcodes and for each barocode serarch
    for matches in the whitelist and assign corrected barocodes if there is an
    unambiquous match.

    :param extract_barcode_tags: path to TSV with
        Index: read_id
        columns: the read tags
    :param whitelist: list of potential barcodes.
    :param: barcode_length: expected lengt of barcode
    :param: max_ed: max allowed edit distance between am uncorrected barcode
        and a potential corected whitelist barcode.
    :param: min_ed_diff: minimum allowed edit distance between top two
        barcode candidates.
    :return:
        barcode counts DataFrame
        read tags DataFrame
    """
    corrected_bcs = []

    df_tags = pd.read_csv(
        extract_barcode_tags, sep='\t', index_col=0)

    barcode_counter = collections.Counter()
    for row in df_tags.itertuples():
        read_id = row.Index
        bc_uncorr = row.CR
        if not bc_uncorr:
            continue

        # No use considering barcodes that are too small
        if len(bc_uncorr) >= barcode_length - max_ed:

            bc_match, bc_match_ed, next_match_diff = \
                calc_ed_with_whitelist(bc_uncorr, whitelist)

            # Check barcode match edit distance and difference to
            # runner-up edit distance.
            if (bc_match_ed <= max_ed) and (next_match_diff >= min_ed_diff):
                corrected_bcs.append([read_id, bc_match])
                barcode_counter[bc_match] += 1

    if len(corrected_bcs) > 0:
        corr_bc_df = pd.DataFrame.from_records(
            corrected_bcs, index='read_id',
            columns=['read_id', 'CB'])
    else:
        return barcode_counter, pd.DataFrame()

    # Join the corrected barcode back to the rest of the orginal tags.
    result_tags_df = df_tags.merge(
        corr_bc_df, how='left', left_index=True, right_index=True)
    result_tags_df.CB.fillna('-', inplace=True)

    return barcode_counter, result_tags_df


def main(args):
    """Run main entry point."""
    whitelist = pd.read_csv(
        args.whitelist, index_col=None, sep='\t', header=None)[0].to_list()

    barcode_counter, tags = \
        process_records(
            args.extract_barcode_tags, whitelist,
            args.barcode_length, args.max_ed, args.min_ed_diff)

    tags.to_csv(args.output_tags, sep='\t')

    with open(args.output_counts, "w") as f:
        for bc, n in barcode_counter.most_common():
            f.write(f"{bc}\t{n}\n")
