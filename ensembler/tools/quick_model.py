import os
import warnings
import pandas as pd
import ensembler
import ensembler.initproject
import ensembler.modeling
import ensembler.refinement
import ensembler.packaging
from ensembler.core import get_templates_resolved_seq
from simtk import unit


class QuickModel(object):
    def __init__(self, targetid=None, templateids=None, target_uniprot_entry_name=None,
                 uniprot_domain_regex=None, pdbids=None, chainids=None, template_uniprot_query=None,
                 model_seqid_cutoff=None, loopmodel=True, package_for_fah=False, nfahclones=None,
                 structure_dirs=None, sim_length=100*unit.picoseconds
                 ):
        """
        Run this after having set up targets and templates with the appropriate ensembler commands.

        :param targetid: str
        :param templateids: list of str
        :param target_uniprot_entry_name: str
        :param uniprot_domain_regex: str
        :param pdbids: list of str
        :param chainids: dict {pdbid (str): [chainid (str)]}
        :param template_uniprot_query: str
        :param model_seqid_cutoff: float
        :param loopmodel: boolean
        :param package_for_fah: boolean
        :param nfahclones: int
        :param structure_dirs: list of str
        :param sim_length: simtk.unit.picoseconds
        """
        self.targetid = targetid
        self.templateids = templateids
        self.target_uniprot_entry_name = target_uniprot_entry_name
        self.uniprot_domain_regex = uniprot_domain_regex
        self.pdbids = pdbids
        self.chainids = chainids
        self.template_uniprot_query = template_uniprot_query
        self.model_seqid_cutoff = model_seqid_cutoff
        self.loopmodel = loopmodel
        self.package_for_fah = package_for_fah
        self.nfahclones = nfahclones
        self.structure_dirs = structure_dirs
        self.sim_length = sim_length

        if not ensembler.core.check_project_toplevel_dir(raise_exception=False):
            ensembler.initproject.InitProject('.')

        if (not self.targetid and not self.target_uniprot_entry_name) or (self.targetid and self.target_uniprot_entry_name):
            raise Exception('Must specify either targetid or target_uniprot_entry_name.')

        if not self.targetid:
            if not self.target_uniprot_entry_name or not self.uniprot_domain_regex:
                raise Exception(
                    'If no targetid is passed, must specify target_uniprot_entry_name and '
                    'uniprot_domain_regex.'
                )
            uniprot_query_string = 'mnemonic:%s' % self.target_uniprot_entry_name
            gather_targets_obj = ensembler.initproject.GatherTargetsFromUniProt(
                uniprot_query_string, uniprot_domain_regex=self.uniprot_domain_regex
            )
            self.targetid = gather_targets_obj.targets[0].id

        existing_templates = False
        if os.path.exists(os.path.join(ensembler.core.default_project_dirnames.templates, 'templates-resolved-seq.fa')):
            all_templates_resolved_seq = get_templates_resolved_seq()
            if len(all_templates_resolved_seq) > 0:
                existing_templates = True

        if self.templateids:
            if not existing_templates:
                raise Exception('No existing templates found.')
        elif self.pdbids:
            ensembler.initproject.gather_templates_from_pdb(self.pdbids, self.uniprot_domain_regex, chainids=self.chainids, structure_dirs=self.structure_dirs)
            templates_resolved_seq = get_templates_resolved_seq()
            self.templateids = [t.id for t in templates_resolved_seq]
        elif self.template_uniprot_query:
            ensembler.initproject.gather_templates_from_uniprot(self.template_uniprot_query, self.uniprot_domain_regex, structure_dirs=self.structure_dirs)
            self._align_all_templates(self.targetid)
            self.templateids = self._select_templates_based_on_seqid_cutoff(self.targetid, seqid_cutoff=self.model_seqid_cutoff)
        else:
            if not existing_templates:
                raise Exception('No existing templates found.')
            self._align_all_templates(self.targetid)
            self.templateids = self._select_templates_based_on_seqid_cutoff(self.targetid, seqid_cutoff=self.model_seqid_cutoff)

        if not self.templateids or len(self.templateids) == 0:
            warnings.warn('No templates found. Exiting.')
            return

        self._model(self.targetid, self.templateids, loopmodel=self.loopmodel, package_for_fah=self.package_for_fah, nfahclones=self.nfahclones)

    def _align_all_templates(self, targetid):
        ensembler.modeling.align_targets_and_templates(process_only_these_targets=targetid)

    def _select_templates_based_on_seqid_cutoff(self, targetid, seqid_cutoff=None):
        """
        If seqid_cutoff is not specified, it will be chosen interactively.
        :param seqid_cutoff:
        :return:
        """
        seqid_filepath = os.path.join(ensembler.core.default_project_dirnames.models, targetid, 'sequence-identities.txt')
        with open(seqid_filepath) as seqid_file:
            seqids_list = [line.split() for line in seqid_file.readlines()]
            templateids = [i[0] for i in seqids_list]
            seqids = [float(i[1]) for i in seqids_list]

        df = pd.DataFrame({
            'templateids': templateids,
            'seqids': seqids,
            })

        if seqid_cutoff is None:
            for cutoff in range(0, 101, 10):
                ntemplates = len(df[df.seqids > cutoff])
                print('Number of templates with seqid > %d: %d' % (cutoff, ntemplates))

            seqid_cutoff_chosen = False
            while not seqid_cutoff_chosen:
                seqid_cutoff = float(raw_input('Choose a sequence identity cutoff for target %s (confirm at next step): ' % targetid))
                ntemplates = len(df[df.seqids > seqid_cutoff])
                print('Number of templates chosen by sequence identity cutoff (%.1f): %d' % (seqid_cutoff, ntemplates))
                confirm_seqid_cutoff = raw_input('Use this sequence identity cutoff? (y|N): ')
                if confirm_seqid_cutoff.lower() in ['y', 'yes']:
                    seqid_cutoff_chosen = True

        selected_templates = df[df.seqids > seqid_cutoff]
        templateids = list(selected_templates.templateids)

        return templateids

    def _model(self, targetid, templateids, loopmodel=True, package_for_fah=False, nfahclones=None):
        if loopmodel:
            ensembler.modeling.model_template_loops(process_only_these_templates=templateids)
        ensembler.modeling.align_targets_and_templates(process_only_these_targets=targetid, process_only_these_templates=templateids)
        ensembler.modeling.build_models(process_only_these_targets=targetid, process_only_these_templates=templateids)
        ensembler.modeling.cluster_models(process_only_these_targets=targetid)
        ensembler.refinement.refine_implicit_md(process_only_these_targets=targetid, process_only_these_templates=templateids, sim_length=self.sim_length)
        ensembler.refinement.solvate_models(process_only_these_targets=targetid, process_only_these_templates=templateids)
        ensembler.refinement.determine_nwaters(process_only_these_targets=targetid, process_only_these_templates=templateids)
        ensembler.refinement.refine_explicit_md(process_only_these_targets=targetid, process_only_these_templates=templateids, sim_length=self.sim_length)
        if package_for_fah:
            if not nfahclones:
                nfahclones = 1
            ensembler.packaging.package_for_fah(process_only_these_targets=targetid, nclones=nfahclones)