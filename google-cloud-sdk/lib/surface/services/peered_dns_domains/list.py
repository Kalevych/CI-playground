# -*- coding: utf-8 -*- #
# Copyright 2020 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""services peered-dns-domains delete command."""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

from googlecloudsdk.api_lib.cloudresourcemanager import projects_api
from googlecloudsdk.api_lib.services import peering
from googlecloudsdk.calliope import base
from googlecloudsdk.command_lib.projects import util as projects_util
from googlecloudsdk.core import properties


@base.ReleaseTracks(base.ReleaseTrack.ALPHA, base.ReleaseTrack.BETA)
class List(base.DescribeCommand):
  """List the peered DNS domains for a private service connection."""

  detailed_help = {
      'DESCRIPTION':
          """\
          This command lists the peered DNS domains for a private service
          connection.
          """,
      'EXAMPLES':
          """\
          To list the peered DNS domains for a private service connection
          between service ``peering-service'' and the consumer network
          ``my-network'' in the current project, run:

            $ {command} --network=my-network --service=peering-service
          """,
  }

  @staticmethod
  def Args(parser):
    """Args is called by calliope to gather arguments for this command.

    Args:
      parser: An argparse parser that you can use to add arguments that go on
        the command line after this command. Positional arguments are allowed.
    """
    parser.add_argument(
        '--network',
        metavar='NETWORK',
        required=True,
        help='Network in the consumer project peered with the service.')
    parser.add_argument(
        '--service',
        metavar='SERVICE',
        default='servicenetworking.googleapis.com',
        help='Name of the service to list the peered DNS domains for.')
    parser.display_info.AddFormat("""
        table(
            name:sort=1,
            dnsSuffix
        )
    """)

  def Run(self, args):
    """Run 'services peered-dns-domains list'.

    Args:
      args: argparse.Namespace, The arguments that this command was invoked
        with.

    Returns:
      The list of peered DNS domains.
    """
    project = properties.VALUES.core.project.Get(required=True)
    project_number = _GetProjectNumber(project)
    domains = peering.ListPeeredDnsDomains(
        project_number,
        args.service,
        args.network,
    )
    return domains


def _GetProjectNumber(project_id):
  return projects_api.Get(projects_util.ParseProject(project_id)).projectNumber
