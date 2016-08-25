import argparse
import os
import subprocess
from defusedxml import ElementTree
from api_counter import APICounter
from analyzer import Analyzer
from function_comparator import FunctionComparator
from renamer import Renamer
from base import find_class_paths_and_iterate, find_class_paths
import base
import shutil
import colorama
from colorama import Fore, Style
from pprint import pprint
import database
from apk import File, Package
import apkdb
from elsim import SimHash

__author__ = 'ohaz'

threads = None


def run(cmd):
    subprocess.run(cmd)


def search_mains(xml_root):
    mains = []
    for application in xml_root:
        if application.tag == 'application':
            for activity in application:
                if activity.tag == 'activity':
                    for intent in activity:
                        if intent.tag == 'intent-filter':
                            for action in intent:
                                if action.tag == 'action':
                                    if 'android.intent.action.MAIN' in action.attrib.values():
                                        mains.append(
                                            activity.attrib['{http://schemas.android.com/apk/res/android}name'])
    return mains


def deobfuscate(path):
    android_manifest = ElementTree.parse(os.path.join(path, 'AndroidManifest.xml'))
    root = android_manifest.getroot()
    mains = search_mains(root)
    print('>> Main activities found:', mains)
    to_read = find_class_paths_and_iterate(path)
    if to_read is None:
        return
    api_counter = APICounter(threads, to_read)
    # TODO ENABLE COUNTING AGAIN
    folded = api_counter.count_and_compare(path)
    shortened = api_counter.shortened
    api_counter_compared = api_counter.compared
    # Renaming
    renamer = Renamer(to_read, path)
    # renamer.rename_package(['a', 'b', 'c', 'd', 'e'], ['new1', 'new2', 'new3', 'new4', 'new5'])
    # renamer.rename_function(['new1', 'new2', 'new3', 'new4', 'new5'], 'A', 'b', 'newname')

    comparator = FunctionComparator(threads, to_read)
    result_map = comparator.analyze_all()
    folded_map = comparator.fold_by_file(result_map)
    function_comparator_compared = comparator.compare_to_db(folded_map)
    analyzer = Analyzer()
    analyzer.analyze(api_counter_compared, function_comparator_compared)

    # signature = comparator.create_function_signature('public', '', 'b', 'Ljava/lang/String;', 'Ljava/lang/String;')
    # comparator.analyze_function_instruction_groups(path, os.path.join('smali', 'a', 'b', 'c', 'd', 'e', 'A.smali'), signature)


def analyze(path):
    android_manifest = ElementTree.parse(os.path.join(path, 'AndroidManifest.xml'))
    root = android_manifest.getroot()
    mains = search_mains(root)
    print('>> Main activities found:', mains)
    to_read = find_class_paths_and_iterate(path)
    if to_read is None:
        return

    # package_to_analyze = input('Name of the Package to analyze (divided by .):')
    # package_to_analyze = package_to_analyze.replace('.', os.sep)

    packages_to_search = ['org.bouncycastle', 'net.java.otr4j.crypto', 'org.sqlite', 'android.support.v4',
                          'android.support.v7', 'android.support.v13']
    packages_to_search = [x.split('.') for x in packages_to_search]

    api_counter = APICounter(threads, to_read)
    folded = api_counter.count(path)
    shortened = api_counter.shortened
    already_in_db = []
    for package in packages_to_search:
        current = shortened
        for e in package:
            if e in current:
                current = current[e]
            else:
                break
        else:
            # Searched for a package and found it!
            lib = database.session.query(database.Library).filter(
                database.Library.base_package == '.'.join(package)).first()
            if not lib:
                lib = database.Library(name='.'.join(package), base_package='.'.join(package))
                database.session.add(lib)
            in_db = False
            for version in lib.versions:
                if version.api_calls == current['.overall']:
                    print('Already in DB:', lib, version)
                    already_in_db.append((str(lib), str(version)))
                    in_db = True
            if not in_db:
                version = database.LibraryVersion(library=lib, api_calls=current['.overall'])
                database.session.add(version)
        database.session.commit()
    return already_in_db


def recursive_iterate(parent):
    for f in os.listdir(parent.get_full_path()):
        if f.endswith('.smali'):
            in_sub_tree = True
            file = File(f, parent)
            parent.add_child_file(file)
        else:
            p = Package(f, parent)
            parent.add_child_package(p)
            recursive_iterate(p)


def new_iterate(path):
    class_paths = find_class_paths(path)
    base.dot_id_counter = 0
    root = Package('ROOT', parent=None, special=True)
    for folder in class_paths:
        special = Package(folder, root, True)
        special.set_special_path(os.path.join(path, folder))
        root.add_child_package(special)
        recursive_iterate(special)
    root.iterate_end_of_packages()
    return root


def new_analyze(path):
    # android_manifest = ElementTree.parse(os.path.join(path, 'AndroidManifest.xml'))
    # root = android_manifest.getroot()
    # mains = search_mains(root)
    # print('>> Main activities found:', mains)

    root = new_iterate(path)

    # from graphviz import Digraph
    # dot = Digraph()
    # root.graph(dot, None, True)
    # dot.render('OUT.png', view=True)
    # with open('out.dot', 'w+') as f:
    #    f.write(dot.source)

    node = root.child_packages[0]
    eops = root.find_eops()
    files = []
    q_methods = apkdb.session.query(apkdb.MethodVersion).all()
    for eop in eops:
        if eop.is_obfuscated() < 0.825:
            print('Saving package to DB:', eop.get_full_package())
            for file in eop.get_files():
                file.generate_methods()
                file.generate_sim_hashes()
                file.generate_ngrams()
            eop.save_to_db()
            continue

        print('Analyzing package:', eop.get_full_package())
        p_dict_simhash = dict()
        p_dict_ngram = dict()
        for file in eop.get_files():
            methods = file.generate_methods()
            possible_files_simhash = dict()
            possible_files_ngram = dict()
            for m in methods:
                m.generate_ngrams()
                if m.is_significant() and 'constructor ' not in m.signature and 'abstract ' not in m.signature:
                    # ngram comparison
                    possible_method_versions_ngram = dict()
                    possible_methods_ngram = dict()
                    for ngram in m.ngrams:
                        q = apkdb.session.query(apkdb.ThreeGram).filter(apkdb.ThreeGram.one == ngram[0],
                                                                        apkdb.ThreeGram.two == ngram[1],
                                                                        apkdb.ThreeGram.three == ngram[2]).all()
                        for ng in q:
                            if ng.method_version_id in possible_method_versions_ngram.keys():
                                possible_method_versions_ngram[ng.method_version_id]['amount'] += 1
                            else:
                                possible_method_versions_ngram[ng.method_version_id] = {'amount': 1,
                                                                                        'method': ng.method_version}

                    for ngram_possibility in possible_method_versions_ngram.values():
                        if ngram_possibility['method'].method.id in possible_methods_ngram:
                            possible_methods_ngram[ngram_possibility['method'].method.id]['amount'] = max(
                                possible_methods_ngram[ngram_possibility['method'].method.id]['amount'],
                                ngram_possibility['amount'])
                        else:
                            possible_methods_ngram[ngram_possibility['method'].method.id] = {
                                'amount': ngram_possibility['amount'], 'method': ngram_possibility['method'].method}
                    s = sorted(possible_methods_ngram.items(), key=lambda x: x[1]['amount'])[-1:-5:-1]
                    pprint(s)
                    print(len(m.ngrams))
                    '''
                    # SimHash comparison
                    simhash = m.elsim_similarity_instructions()
                    possible_methods_simhash = dict()
                    for compare_method_v in q_methods:
                        sim = simhash.similarity(SimHash.from_string(compare_method_v.elsim_instr_hash))
                        if sim >= 0.9:
                            if compare_method_v.method.id not in possible_methods_simhash.keys():
                                possible_methods_simhash[compare_method_v.method.id] = compare_method_v.method
                    for method in possible_methods_simhash.values():
                        if method.file.id not in possible_files_simhash:
                            possible_files_simhash[method.file.id] = {'file': method.file, 'amount': 1}
                        else:
                            possible_files_simhash[method.file.id]['amount'] += 1
            for p in possible_files_simhash.values():
                if p['file'].package.library.base_package in p_dict_simhash:
                    p_dict_simhash[p['file'].package.library.base_package] += p['amount']
                else:
                    p_dict_simhash[p['file'].package.library.base_package] = p['amount']
                    '''
        print()
        print(eop.get_full_package())
        if p_dict_simhash:
            print(sorted(p_dict_simhash.items(), key=lambda x: x[1], reverse=True))
        if p_dict_ngram:
            print(sorted(p_dict_ngram.items(), key=lambda x: x[1], reverse=True))

    """for f in files:
        for e in files:
            if e != f:
                filesim = 0
                for method in f.methods:
                    if not method.is_significant():
                        continue
                    fhash = method.elsim_similarity_instructions()
                    for m_2 in e.methods:
                        if not m_2.is_significant():
                            continue
                        ehash = m_2.elsim_similarity_instructions()
                        sim = fhash.similarity(ehash)
                        if sim > 0.9:
                            filesim += 1
                if len(f.methods) > 4 and float(filesim) / float(len(f.methods)) > 0.8:
                    print(f.name, '==', e.name)"""


def main():
    global threads
    parser = argparse.ArgumentParser(description='Deobfuscate Android Applications')
    parser.add_argument('apk', metavar='apk', type=str, help='The apk to unpack')
    parser.add_argument('-t', '--threads', dest='threads', action='store', nargs=1, type=int,
                        help='Maximum amount of threads used', default=4)
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Show more detailed information')
    parser.add_argument('-k', '--keep', dest='keep', action='store_true', help='Keep old folder')
    parser.add_argument('-sd', '--skip-decompile', dest='skip_decompile', action='store_true',
                        help='Skip decompilation')
    parser.add_argument('-sb', '--skip-build', dest='skip_build', action='store_true',
                        help='Skip recompilation / rebuilding apk')
    parser.add_argument('-s', '--skip', dest='skip_all', action='store_true', help='Skip all')
    parser.add_argument('-a', '--analyze', dest='analyze', action='store_true',
                        help='Analyze instead of deobfuscate. With this, you can add new stuff to the database.')
    args = parser.parse_args()

    colorama.init()

    apk_paths = os.path.abspath(args.apk)
    threads = args.threads
    if isinstance(threads, list):
        threads = threads[0]
    args.skip_decompile = True if args.skip_all else args.skip_decompile
    args.skip_build = True if args.skip_all else args.skip_build

    if os.path.isdir(apk_paths):
        apks = [os.path.join(apk_paths, x) for x in os.listdir(apk_paths) if x.endswith('.apk')]
    else:
        apks = [apk_paths]

    base.verbose = args.verbose
    already_in_db = []
    for apk in apks:
        output_folder = os.path.basename(apk)[:-4]

        print(Fore.GREEN + '> Starting deobfuscation process for:', apk)
        print('---------------------------------------------')
        print(Style.RESET_ALL)
        if not args.keep and os.path.exists(output_folder):
            print(Fore.RED + '>> Removing old output folder')
            print(Style.RESET_ALL)
            shutil.rmtree(output_folder)
        if not args.skip_decompile:
            run(['java', '-jar', 'apktool.jar', 'd', apk])
            print(Fore.BLUE + '>> Decompiling to smali code done')
        print(Style.RESET_ALL)
        if not args.analyze:
            deobfuscate(os.path.join(os.getcwd(), output_folder))
            print(Fore.GREEN + '---------------------------------------------')
            print('Done deobfuscating...' + Style.RESET_ALL)
            if not args.skip_build:
                print('Rebuilding APK')
                run(['java', '-jar', 'apktool.jar', 'b', os.path.join(os.getcwd(), output_folder), '-o',
                     apk + '_new.apk'])
                if args.verbose:
                    base.verbose = True
                    print(Fore.LIGHTRED_EX + '---------------------------------------------')
                    print('Don\'t forget to sign your apk with the following commands:')
                    print(
                        'keytool -genkey -v -keystore my-release-key.keystore -alias alias_name -keyalg RSA -keysize 2048 -validity 10000')
                    print(
                        'jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 -keystore my-release-key.keystore my_application.apk alias_name')
                    print('jarsigner -verify -verbose -certs my_application.apk')
                    print('zipalign -v 4 your_project_name-unaligned.apk your_project_name.apk')
        else:
            new_analyze(os.path.join(os.getcwd(), output_folder))
            # TODO: already_in_db.extend(analyze(os.path.join(os.getcwd(), output_folder)))

        if not args.keep and os.path.exists(output_folder):
            print(Fore.RED + '>> Removing output folder')
            print(Style.RESET_ALL)
            try:
                shutil.rmtree(output_folder)
            except OSError as e:
                print('Failed to remove folder', output_folder)
    if args.analyze:
        print(Fore.GREEN)
        pprint(already_in_db)
        print(Style.RESET_ALL)


if __name__ == '__main__':
    main()
